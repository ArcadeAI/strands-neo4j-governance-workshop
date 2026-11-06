"""A record of every tool call a run made and what came back: for the terminal, the tests and the evals."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    status: str = ""
    text: str = ""

    @property
    def refused(self) -> bool:
        return self.status == "error"


def _text(result: dict[str, Any]) -> str:
    parts = []
    for block in result.get("content", []):
        if "text" in block:
            parts.append(block["text"])
        elif "json" in block:
            parts.append(json.dumps(block["json"], default=str))
    return "\n".join(parts)


@dataclass
class Transcript(HookProvider):
    echo: Callable[[ToolCall], None] | None = None
    calls: list[ToolCall] = field(default_factory=list)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterToolCallEvent, self._after)

    def _after(self, event: AfterToolCallEvent) -> None:
        call = ToolCall(
            name=event.tool_use["name"],
            input=dict(event.tool_use.get("input") or {}),
            status=event.result.get("status", ""),
            text=_text(event.result),
        )
        self.calls.append(call)
        if self.echo:
            self.echo(call)

    def names(self) -> list[str]:
        return [c.name for c in self.calls]


def print_call(call: ToolCall, stream=sys.stderr, width: int = 220) -> None:
    mark = "x" if call.refused else ">"
    args = json.dumps(call.input, default=str)
    text = " ".join(call.text.split())
    if len(text) > width:
        text = text[: width - 1] + "…"
    print(f"  {mark} {call.name} {args}\n      {text}", file=stream)
