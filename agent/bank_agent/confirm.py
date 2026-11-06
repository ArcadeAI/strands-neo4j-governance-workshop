"""Ask the person before the agent acts on their behalf.

This is consent, not authority. It stops the agent from sending an email, posting to Slack or
asking to freeze an account without the investigator seeing it first. It does not decide
whether the action is allowed: that lives in the control plane, where a prompt or a different
client cannot reach it, and a call the person allows here can still be refused there.

It uses Strands interrupts: the run stops with `stop_reason == "interrupt"` (or a Graph with
`Status.INTERRUPTED`), and the caller resumes it with the person's answer (`cli.run_with_confirmation`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from bank_agent.arcade_tools import SELECT, toolkit_of

INTERRUPT = "bank.confirm"
YES = {"y", "yes", "approve", "allow", "true"}


class ConfirmActions(HookProvider):
    """Interrupt before any tool outside the bank's own toolkit, and before the named bank tools."""

    def __init__(self, internal: Iterable[str] = ("Bank",), also: Iterable[str] = (), local: Iterable[str] = (SELECT, "fx_convert")) -> None:
        self.internal = {name.lower() for name in internal}
        self.also = set(also)
        self.local = set(local)

    def needs_consent(self, tool_name: str) -> bool:
        if tool_name in self.also:
            return True
        if tool_name in self.local or tool_name == "handoff_to_agent":
            return False
        return toolkit_of(tool_name).lower() not in self.internal

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before)

    def _before(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use["name"]
        if not self.needs_consent(name):
            return
        answer = event.interrupt(INTERRUPT, reason={"tool": name, "input": event.tool_use.get("input") or {}})
        if str(answer).strip().lower() not in YES:
            event.cancel_tool = f"The person declined to run {name}. Do not retry it; ask what they want instead."
