"""Arcade tools for a Strands agent: the counterpart of LangChain's `ArcadeMiddleware`.

The agent lists no loan desk tools in code. Every run starts with:

- the loan desk toolkit as Arcade lists it for the signed-in person (`GET /v1/tools?toolkit=LoanDesk`).
  The listing goes through the control plane's access hook, so a credit analyst's agent never
  even sees `LoanDesk_ApproveLoan`;
- `arcade_select_tools`, a tool the model calls to find anything else (Slack, Gmail) through
  Arcade's Tool Recommendation. What it finds is registered on the running agent, and Strands
  offers it to the model on the very next step.

Every call goes through the Arcade Engine with the project key, as one person. The loan desk
runs as the persona (`LOAN_DESK_USER`), the identity the hooks hold to a role and a clearance.
Other toolkits run as `CONNECTED_APPS_USER` when it is set: Arcade's built-in Slack and Gmail
apps bind a grant to the Arcade account that authorizes it, so they have to run as you.

Nothing here decides whether a call may run. A refusal comes back from Arcade, in the words
the control plane wrote, and is handed to the model as the tool's result.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from strands import tool
from strands.tools.tools import PythonAgentTool
from strands.types.tools import ToolContext, ToolResult, ToolUse

SELECT = "arcade_select_tools"
MIN_TOP_K = 10


@dataclass(frozen=True)
class ArcadeToolDef:
    """One Arcade tool as the agent needs it: its name, version, description and parameters."""

    qualified: str
    toolkit: str
    description: str = ""
    parameters: Any = None
    version: str | None = None

    @property
    def model_name(self) -> str:
        return model_name(self.qualified)


def model_name(qualified: str) -> str:
    """`LoanDesk.ApproveLoan` as the model sees it: `LoanDesk_ApproveLoan`."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", qualified.split("@", 1)[0])[:64]


def toolkit_of(name: str) -> str:
    """`LoanDesk` from `LoanDesk.SearchLoans@1.0.0` or `LoanDesk_SearchLoans`."""
    base = name.split("@", 1)[0]
    for separator in (".", "_"):
        if separator in base:
            return base.split(separator, 1)[0]
    return base


_TYPES = {"string": "string", "integer": "integer", "number": "number", "float": "number",
          "boolean": "boolean", "json": "object", "object": "object", "array": "array"}


def _value_schema(schema: dict[str, Any]) -> dict[str, Any]:
    kind = _TYPES.get(str(schema.get("val_type")), "string")
    out: dict[str, Any] = {"type": kind}
    if kind == "array":
        out["items"] = {"type": _TYPES.get(str(schema.get("inner_val_type")), "string")}
    if schema.get("enum"):
        out["enum"] = list(schema["enum"])
    return out


def json_schema(parameters: Any) -> dict[str, Any]:
    """Arcade's parameter descriptors as the JSON Schema a Strands tool spec takes.

    The tool list and Tool Rec hand out Arcade descriptors (`name`, `required`, `value_schema`);
    a suggestion may already carry JSON Schema, which passes through.
    """
    if isinstance(parameters, dict) and parameters:
        return parameters
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in parameters or []:
        if hasattr(parameter, "model_dump"):
            parameter = parameter.model_dump()
        name = parameter.get("name")
        if not name:
            continue
        schema = _value_schema(parameter.get("value_schema") or {})
        if parameter.get("description"):
            schema["description"] = " ".join(str(parameter["description"]).split())
        properties[name] = schema
        if parameter.get("required"):
            required.append(name)
    return {"type": "object", "properties": properties, **({"required": required} if required else {})}


@dataclass
class Outcome:
    """What one call through Arcade came back with: a value, a refusal or error, or a link to authorize."""

    value: Any = None
    error: str | None = None
    guidance: str | None = None
    auth_url: str | None = None


class Engine(Protocol):
    def list_toolkit(self, toolkit: str, user_id: str) -> list[ArcadeToolDef]: ...
    def select(self, tasks: list[str], user_id: str, limit: int) -> tuple[str, list[ArcadeToolDef]]: ...
    def execute(self, tool: ArcadeToolDef, inputs: dict[str, Any], user_id: str, query_id: str = "") -> Outcome: ...


def _definition(item: Any) -> ArcadeToolDef | None:
    data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
    fqn = data.get("fully_qualified_name") or data.get("qualified_name") or data.get("tool_name") or ""
    if not fqn:
        return None
    name, _, version = fqn.partition("@")
    toolkit = data.get("toolkit")
    toolkit_name = toolkit.get("name") if isinstance(toolkit, dict) else toolkit or toolkit_of(name)
    toolkit_version = toolkit.get("version") if isinstance(toolkit, dict) else None
    params = data.get("input")
    params = params.get("parameters") if isinstance(params, dict) else data.get("input_schema")
    return ArcadeToolDef(
        qualified=name, toolkit=toolkit_name, description=data.get("description") or "",
        parameters=params or [], version=version or data.get("version") or toolkit_version or None,
    )


def _error_text(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        for key in ("message", "error", "msg"):
            if isinstance(body.get(key), str):
                return body[key]
    return str(exc)


class ArcadeEngine:
    """`Engine` over the `arcadepy` client."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def connect(cls, api_key: str, base_url: str = "") -> ArcadeEngine:
        from arcadepy import Arcade

        return cls(Arcade(api_key=api_key, **({"base_url": base_url} if base_url else {})))

    def list_toolkit(self, toolkit: str, user_id: str) -> list[ArcadeToolDef]:
        tools = []
        for item in self._client.tools.list(toolkit=toolkit, user_id=user_id, limit=100):
            definition = _definition(item)
            if definition and definition.toolkit.lower() == toolkit.lower():
                tools.append(definition)
        return tools

    def select(self, tasks: list[str], user_id: str, limit: int) -> tuple[str, list[ArcadeToolDef]]:
        # TODO(arcade): Tool Recommendation (`POST /v1/tools/select`) has no typed method in arcadepy
        # 1.10; this is the body both Arcade reference workshops send. Switch to the SDK method once
        # one ships.
        payload = self._client.post(
            "/v1/tools/select",
            body={"tasks": tasks, "top_k": max(limit, MIN_TOP_K), "user_id": user_id},
            cast_to=object,
        )
        payload = payload if isinstance(payload, dict) else {}
        found: dict[str, ArcadeToolDef] = {}
        for result in payload.get("results") or []:
            for suggestion in (result.get("suggestions") or [])[:limit]:
                definition = _definition(suggestion)
                if definition and definition.qualified not in found:
                    found[definition.qualified] = self._current(definition, user_id)
        return str(payload.get("query_id") or ""), list(found.values())

    def _current(self, definition: ArcadeToolDef, user_id: str) -> ArcadeToolDef:
        """The catalog's own definition, which can be newer than the schema Tool Rec handed out."""
        try:
            current = _definition(self._client.tools.get(definition.qualified, user_id=user_id))
        except Exception:  # noqa: BLE001 - the suggestion's own schema stands
            return definition
        return current or definition

    def execute(self, tool: ArcadeToolDef, inputs: dict[str, Any], user_id: str, query_id: str = "") -> Outcome:
        options: dict[str, Any] = {"tool_name": tool.qualified, "input": inputs, "user_id": user_id}
        if tool.version:
            options["tool_version"] = tool.version
        if query_id:
            options["extra_body"] = {"query_id": query_id}
        # TODO(arcade): confirm how a pre hook's CHECK_FAILED reaches the caller of /v1/tools/execute:
        # as output.error with the hook's error_message (handled below) or as an HTTP error (handled here).
        try:
            response = self._client.tools.execute(**options)
        except Exception as exc:  # noqa: BLE001 - a refusal or an outage is an answer the model can read
            message = _error_text(exc)
            if "authoriz" in message.lower():
                url = self._authorize(tool, user_id)
                if url:
                    return Outcome(auth_url=url)
            return Outcome(error=message)
        output = response.output
        authorization = getattr(output, "authorization", None) if output else None
        if authorization and authorization.url and authorization.status != "completed":
            return Outcome(auth_url=authorization.url)
        error = getattr(output, "error", None) if output else None
        if response.success is False or error:
            message = error.message if error else "The tool call failed."
            if error and ("AUTH" in str(error.kind).upper() or "authoriz" in message.lower()):
                url = self._authorize(tool, user_id)
                if url:
                    return Outcome(auth_url=url)
            return Outcome(error=message, guidance=getattr(error, "additional_prompt_content", None))
        return Outcome(value=output.value if output else None)

    def _authorize(self, tool: ArcadeToolDef, user_id: str) -> str:
        try:
            response = self._client.tools.authorize(tool_name=tool.qualified, user_id=user_id)
        except Exception:  # noqa: BLE001
            return ""
        return "" if response.status == "completed" else (response.url or "")


def result_of(tool_use: ToolUse, outcome: Outcome, toolkit: str) -> ToolResult:
    """One Arcade outcome as the tool result the model reads."""
    if outcome.auth_url:
        text = (
            f"AUTHORIZATION REQUIRED: {toolkit} needs the person's permission before this can run. "
            f"Give them this link, then stop until they say they have allowed it: {outcome.auth_url}"
        )
        return {"toolUseId": tool_use["toolUseId"], "status": "error", "content": [{"text": text}]}
    if outcome.error is not None:
        text = outcome.error + (f"\n{outcome.guidance}" if outcome.guidance else "")
        return {"toolUseId": tool_use["toolUseId"], "status": "error", "content": [{"text": text}]}
    value = outcome.value
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return {"toolUseId": tool_use["toolUseId"], "status": "success", "content": [{"text": text}]}


@dataclass
class ArcadeToolbox:
    """The Arcade tools for one person's agent, and the identity each one runs as."""

    engine: Engine
    persona: str
    connected_apps_user: str = ""
    toolkit: str = "LoanDesk"
    per_task: int = 5
    links: list[str] = field(default_factory=list)

    def identity_for(self, definition: ArcadeToolDef) -> str:
        """The loan desk runs as the persona; anything else as the person's own Arcade account, when set."""
        if self.connected_apps_user and definition.toolkit.lower() != self.toolkit.lower():
            return self.connected_apps_user
        return self.persona

    def strands_tool(self, definition: ArcadeToolDef, query_id: str = "") -> PythonAgentTool:
        spec = {
            "name": definition.model_name,
            "description": definition.description or definition.qualified,
            "inputSchema": {"json": json_schema(definition.parameters)},
        }

        def run(tool_use: ToolUse, **_state: Any) -> ToolResult:
            outcome = self.engine.execute(definition, tool_use.get("input") or {}, self.identity_for(definition), query_id)
            if outcome.auth_url and outcome.auth_url not in self.links:
                self.links.append(outcome.auth_url)
            return result_of(tool_use, outcome, definition.toolkit)

        return PythonAgentTool(definition.model_name, spec, run)

    def pinned(self) -> list[PythonAgentTool]:
        """The loan desk toolkit as Arcade lists it for the persona, after the access hook; empty if it cannot be read."""
        try:
            definitions = self.engine.list_toolkit(self.toolkit, self.persona)
        except Exception:  # noqa: BLE001 - the selector still works without the pinned list
            return []
        return [self.strands_tool(d) for d in definitions]

    def select_tool(self):
        toolbox = self

        @tool(name=SELECT, context=True)
        def arcade_select_tools(tasks: list[str], tool_context: ToolContext) -> str:
            """Find the external tools for a task (Slack, email, anything not already in your tool list) and make them callable. Write one plain-English task per workflow. The tools it finds are available on your next step: call them by name."""
            try:
                query_id, found = toolbox.engine.select(tasks, toolbox.persona, toolbox.per_task)
            except Exception as exc:  # noqa: BLE001
                return f"Tool Recommendation could not be reached ({exc})."
            registry = tool_context.agent.tool_registry
            added = []
            for definition in found:
                if definition.model_name == SELECT or definition.model_name in registry.registry:
                    continue
                registry.register_tool(toolbox.strands_tool(definition, query_id))
                added.append(definition)
            if not added:
                return "No new tools matched, or your access policy offers none for this. Rephrase the task, or tell the person."
            return "Now callable:\n" + "\n".join(f"- {d.model_name}: {one_line(d.description)}" for d in added)

        return arcade_select_tools

    def tools(self) -> list[Any]:
        return [self.select_tool(), *self.pinned()]


def one_line(text: str, limit: int = 160) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def names(tools: Iterable[Any]) -> list[str]:
    return [t.tool_name for t in tools]
