"""A model that needs no key: for a first run, for the tests, and for rehearsing without spend.

A `ScriptedModel` is a Strands `Model` whose next move is a function of the conversation so
far. Its default script lists the payment exceptions if the Bank tools are there, and
otherwise says it is scripted. Each desk has its own default scripts for its agents (a naive
screener, a tracer that follows the money), so `uv run ask --desk payments` rehearses the whole
desk with no key. Tests pass their own steps, so a whole governed loop (refusal, escalation,
approval, retry) runs end to end with no model provider at all.

Set MODEL_PROVIDER (bedrock or anthropic) in `.env` to give the agent a real model.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from strands.models.model import Model


@dataclass(frozen=True)
class Call:
    """Call one tool."""

    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class Say:
    """Answer and end the turn."""

    text: str


Move = Call | Say


@dataclass(frozen=True)
class Step:
    """One tool call the conversation already holds, with what came back."""

    name: str
    input: dict[str, Any]
    status: str
    text: str


def tool_history(messages: Sequence[dict[str, Any]]) -> list[Step]:
    """Every tool call in `messages` paired with its result, oldest first."""
    uses: dict[str, tuple[str, dict[str, Any]]] = {}
    steps: list[Step] = []
    for message in messages:
        for block in message.get("content", []):
            if "toolUse" in block:
                use = block["toolUse"]
                uses[use["toolUseId"]] = (use["name"], use.get("input") or {})
            elif "toolResult" in block:
                result = block["toolResult"]
                name, given = uses.get(result["toolUseId"], ("?", {}))
                text = "\n".join(
                    c["text"] if "text" in c else json.dumps(c.get("json")) for c in result.get("content", []) if "text" in c or "json" in c
                )
                steps.append(Step(name, given, result.get("status", "success"), text))
    return steps


def turn_history(messages: Sequence[dict[str, Any]]) -> list[Step]:
    """The tool calls since the last thing the person typed."""
    for i in range(len(messages) - 1, -1, -1):
        content = messages[i].get("content", [])
        if messages[i].get("role") == "user" and any("text" in block for block in content):
            return tool_history(messages[i:])
    return tool_history(messages)


def last_prompt(messages: Sequence[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            texts = [block["text"] for block in message.get("content", []) if "text" in block]
            if texts:
                return "\n".join(texts)
    return ""


def texts(messages: Sequence[dict[str, Any]]) -> str:
    """Every text in the conversation, prompts and tool results alike, oldest first."""
    parts: list[str] = []
    for message in messages:
        for block in message.get("content", []):
            if "text" in block:
                parts.append(block["text"])
            for key in ("toolResult", "toolUse"):
                if key in block:
                    inner = block[key]
                    parts.append(json.dumps(inner.get("input") or {}))
                    parts += [c["text"] for c in inner.get("content", []) if "text" in c]
    return "\n".join(parts)


def find(messages: Sequence[dict[str, Any]], pattern: str) -> str | None:
    """The first match of `pattern` anywhere in the conversation (group 1 if it has one)."""
    match = re.search(pattern, texts(messages))
    if match is None:
        return None
    return match.group(1) if match.groups() else match.group(0)


def payload(step: Step) -> Any:
    """A tool result as data, when it is JSON."""
    try:
        return json.loads(step.text)
    except (TypeError, ValueError):
        return None


Script = Callable[[Sequence[dict[str, Any]], list[str]], Move]


def default_script(messages: Sequence[dict[str, Any]], tool_names: list[str]) -> Move:
    history = turn_history(messages)
    if not history:
        if "Bank_ListPaymentExceptions" in tool_names:
            return Call("Bank_ListPaymentExceptions", {})
        return Say(
            "I'm Bowser Capital's assistant, running on a scripted model with no bank tools connected yet. "
            "Set MODEL_PROVIDER in .env to give me a real model, and ARCADE_API_KEY to connect the bank."
        )
    last = history[-1]
    return Say(f"{last.name} returned:\n\n{last.text[:1500]}")


def steps(*moves: Move | Callable[[list[Step]], Move]) -> Script:
    """A script that plays `moves` in order, one per model turn since the person last spoke.

    A move may be a function of the turn's tool history, for a step that depends on what the
    last call returned. After the last move, the model answers with the last result.
    """

    def script(messages: Sequence[dict[str, Any]], _tool_names: list[str]) -> Move:
        history = turn_history(messages)
        index = len(history)
        if index < len(moves):
            move = moves[index]
            return move(history) if callable(move) else move
        return Say(history[-1].text if history else "")

    return script


class ScriptedModel(Model):
    def __init__(self, script: Script = default_script) -> None:
        self.script = script
        self.config: dict[str, Any] = {"model_id": "scripted"}
        self.seen_tools: list[list[str]] = []

    def get_config(self) -> dict[str, Any]:
        return self.config

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):  # type: ignore[override]
        raise NotImplementedError("The scripted model does not produce structured output; use a real model as the judge.")
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override]
        names = [spec["name"] for spec in tool_specs or []]
        self.seen_tools.append(names)
        move = self.script(messages, names)
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(move, Call):
            tool_use_id = f"scripted-{sum(len(m.get('content', [])) for m in messages)}"
            yield {"contentBlockStart": {"start": {"toolUse": {"name": move.name, "toolUseId": tool_use_id}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(move.input)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": move.text}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
