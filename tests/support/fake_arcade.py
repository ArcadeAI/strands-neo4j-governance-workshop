"""A stand-in for the Arcade Engine: the agent's `Engine`, with the real hooks and the real tools behind it.

What it keeps real is everything this repo owns:

- the tool definitions are what `arcade-mcp-server` derives from the Bank functions;
- every Bank listing goes through the control plane's access hook, every Bank call through its
  pre and post hooks, and every Gmail or Slack call through its pre hook, over HTTP, with the
  bearer token, exactly as Arcade would send them;
- the Bank functions themselves run, against an in-memory graph.

What it stands in for is Arcade's side: routing, the hook calls, OAuth for the connected apps
(a fake Slack and Gmail that ask for authorization once per user), and Tool Recommendation (a
keyword match).

TODO(arcade): the exact payload Arcade sends each hook is taken from the Contextual Access
webhook reference (docs.arcade.dev/en/references/contextual-access-webhook-api); re-check it
against a live hook capture before relying on fields beyond user_id, tool, inputs and output.

TODO(arcade): this assumes Arcade calls a project's pre hook for Arcade-hosted toolkits (Gmail,
Slack) as well as for your own MCP server. Confirm on a live project before relying on the
tipping-off rule; if it does not, the rule needs a wrapper tool in the Bank toolkit instead.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import enum
import itertools
import typing
from dataclasses import dataclass, field
from typing import Any

from arcade_core.catalog import ToolCatalog
from arcade_core.errors import ToolExecutionError
from arcade_core.schema import ToolContext, ToolSecretItem
from fastapi.testclient import TestClient

from bank_agent.arcade_tools import ArcadeToolDef, Outcome
from bank_gate.audit import AuditLog
from bank_gate.policy import Policy, load_policy
from bank_gate.server import create_app
from support.memory_graph import MemoryGraph

TOOLKIT = "Bank"
VERSION = "1.0.0"
TOKEN = "test-gate-token"


def bank_functions() -> list[Any]:
    from bank_tools import aml, approvals, banker, payments

    return [
        payments.list_payment_exceptions, payments.get_payment, payments.screen_party, payments.release_payment, payments.hold_payment,
        aml.get_case, aml.trace_funds, aml.trace_ownership, aml.freeze_account, aml.file_sar,
        banker.search_companies, banker.get_company_profile, banker.list_deals, banker.get_deal,
        approvals.request_approval, approvals.list_approvals, approvals.decide,
    ]


def bank_definitions() -> dict[str, tuple[ArcadeToolDef, Any]]:
    found = {}
    for func in bank_functions():
        definition = ToolCatalog.create_tool_definition(func, TOOLKIT, VERSION)
        found[definition.name] = (
            ArcadeToolDef(
                qualified=f"{TOOLKIT}.{definition.name}",
                toolkit=TOOLKIT,
                description=definition.description,
                parameters=[p.model_dump() for p in definition.input.parameters],
                version=VERSION,
            ),
            func,
        )
    return found


def _enum_of(annotation: Any) -> type[enum.Enum] | None:
    if typing.get_origin(annotation) is typing.Annotated:
        annotation = typing.get_args(annotation)[0]
    for candidate in (annotation, *typing.get_args(annotation)):
        if isinstance(candidate, type) and issubclass(candidate, enum.Enum):
            return candidate
    return None


def _coerce(func: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    """Arguments as Arcade's runtime hands them to the function: enum values as enum members."""
    hints = typing.get_type_hints(func, include_extras=True)
    out = {}
    for name, value in inputs.items():
        kind = _enum_of(hints.get(name))
        out[name] = kind(value) if kind and value is not None else value
    return out


def _run(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coro).result()


@dataclass
class ConnectedApp:
    """A fake third-party toolkit behind OAuth: the first call per user returns a link to authorize."""

    toolkit: str
    tools: dict[str, tuple[str, tuple[str, ...]]]
    keywords: tuple[str, ...]
    authorized: set[str] = field(default_factory=set)
    sent: list[dict[str, Any]] = field(default_factory=list)

    def definitions(self) -> list[ArcadeToolDef]:
        return [
            ArcadeToolDef(
                qualified=f"{self.toolkit}.{name}", toolkit=self.toolkit, description=description, version="1.0.0",
                parameters={"type": "object", "properties": {p: {"type": "string"} for p in params}, "required": list(params)},
            )
            for name, (description, params) in self.tools.items()
        ]


def default_apps() -> list[ConnectedApp]:
    """Slack and Gmail with the parameter names Arcade's own toolkits use."""
    return [
        ConnectedApp("Slack", {"SendDmToUser": ("Send a direct message to a Slack user.", ("user_name", "message"))},
                     ("slack", "dm", "direct message")),
        ConnectedApp("Gmail", {"SendEmail": ("Send an email from the user's Gmail account.", ("recipient", "subject", "body"))},
                     ("email", "gmail", "mail")),
    ]


@dataclass
class Execution:
    tool: str
    user_id: str
    inputs: dict[str, Any]
    outcome: Outcome


class FakeArcadeEngine:
    def __init__(self, graph: MemoryGraph | None = None, policy: Policy | None = None, apps: list[ConnectedApp] | None = None) -> None:
        from bank_tools.graph import use_book

        self.graph = graph or MemoryGraph()
        self.audit = AuditLog(echo=False)
        self.gate = TestClient(create_app(policy or load_policy(), self.graph, TOKEN, self.audit))
        self.tools = bank_definitions()
        self.apps = apps if apps is not None else default_apps()
        self.executions: list[Execution] = []
        self._ids = itertools.count(1)
        use_book(lambda _context: self.graph.book())

    def close(self) -> None:
        from bank_tools.graph import use_book

        use_book(None)

    def _hook(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.gate.post(f"/hooks/{name}", json=payload, headers={"Authorization": f"Bearer {TOKEN}"})
        response.raise_for_status()
        return response.json()

    # Engine

    def list_toolkit(self, toolkit: str, user_id: str) -> list[ArcadeToolDef]:
        if toolkit != TOOLKIT:
            return [d for app in self.apps if app.toolkit == toolkit for d in app.definitions()]
        listing = {"tools": {name: [VERSION] for name in self.tools}}
        answer = self._hook("access", {"user_id": user_id, "toolkits": {TOOLKIT: listing}})
        hidden = set(((answer.get("deny") or {}).get(TOOLKIT) or {}).get("tools") or {})
        return [definition for name, (definition, _) in self.tools.items() if name not in hidden]

    def select(self, tasks: list[str], user_id: str, limit: int) -> tuple[str, list[ArcadeToolDef]]:
        text = " ".join(tasks).lower()
        found = [d for app in self.apps if any(k in text for k in app.keywords) for d in app.definitions()]
        return f"q-{next(self._ids)}", found[:limit]

    def execute(self, tool: ArcadeToolDef, inputs: dict[str, Any], user_id: str, query_id: str = "") -> Outcome:
        outcome = self._execute(tool, dict(inputs), user_id)
        self.executions.append(Execution(tool.qualified, user_id, dict(inputs), outcome))
        return outcome

    def _execute(self, tool: ArcadeToolDef, inputs: dict[str, Any], user_id: str) -> Outcome:
        execution_id = f"exec-{next(self._ids)}"
        toolkit, _, name = tool.qualified.partition(".")
        if toolkit != TOOLKIT:
            return self._connected(toolkit, name, inputs, user_id)

        entry = self.tools.get(name)
        if entry is None:
            return Outcome(error=f"No tool {tool.qualified}.")
        listed = {d.qualified for d in self.list_toolkit(TOOLKIT, user_id)}
        if tool.qualified not in listed:
            return Outcome(error=f"{tool.qualified} is not available to {user_id}.")

        about = {"execution_id": execution_id, "tool": {"toolkit": TOOLKIT, "name": name, "version": VERSION},
                 "context": {"user_id": user_id}}
        pre = self._hook("pre", {**about, "inputs": inputs})
        if pre.get("code") != "OK":
            return Outcome(error=pre.get("error_message") or "Refused by a pre-execution hook.")
        inputs = ((pre.get("override") or {}).get("inputs")) or inputs

        _, func = entry
        context = ToolContext(user_id=user_id, secrets=[ToolSecretItem(key=k, value="memory") for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")])
        try:
            value = _run(func(context, **_coerce(func, inputs)))
        except ToolExecutionError as exc:
            return Outcome(error=exc.message)
        except TypeError as exc:
            return Outcome(error=f"Invalid arguments for {tool.qualified}: {exc}")

        post = self._hook("post", {**about, "inputs": inputs, "output": value})
        if post.get("code") != "OK":
            return Outcome(error=post.get("error_message") or "Refused by a post-execution hook.")
        return Outcome(value=((post.get("override") or {}).get("output")) or value)

    def _connected(self, toolkit: str, name: str, inputs: dict[str, Any], user_id: str) -> Outcome:
        app = next((a for a in self.apps if a.toolkit == toolkit), None)
        if app is None or name not in app.tools:
            return Outcome(error=f"No tool {toolkit}.{name}.")
        if user_id not in app.authorized:
            return Outcome(auth_url=f"https://example.invalid/authorize/{toolkit.lower()}?user={user_id}")
        about = {"execution_id": f"exec-{next(self._ids)}", "tool": {"toolkit": toolkit, "name": name, "version": "1.0.0"},
                 "context": {"user_id": user_id}}
        pre = self._hook("pre", {**about, "inputs": inputs})
        if pre.get("code") != "OK":
            return Outcome(error=pre.get("error_message") or "Refused by a pre-execution hook.")
        app.sent.append({"tool": name, "user_id": user_id, **inputs})
        return Outcome(value={"ok": True})

    def authorize(self, toolkit: str, user_id: str) -> None:
        next(a for a in self.apps if a.toolkit == toolkit).authorized.add(user_id)
