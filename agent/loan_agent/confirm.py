"""Ask the person before the agent sends anything outside the bank.

This is consent, not authority. It stops the agent from posting to Slack or sending an email
on your behalf without you seeing it first. It does not decide whether a loan may be approved:
that lives in the control plane, where a prompt or a different client cannot reach it.

It uses Strands interrupts: the run stops with `stop_reason == "interrupt"`, and the caller
resumes it with the person's answer (see `cli.run_with_confirmation`).
"""

from __future__ import annotations

from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from loan_agent.arcade_tools import SELECT, toolkit_of

INTERRUPT = "loan_desk.confirm_outbound"


class ConfirmOutbound(HookProvider):
    def __init__(self, internal: tuple[str, ...] = ("LoanDesk",), local: tuple[str, ...] = ("loan_payment", SELECT)) -> None:
        self.internal = {name.lower() for name in internal}
        self.local = set(local)

    def outbound(self, tool_name: str) -> bool:
        return tool_name not in self.local and toolkit_of(tool_name).lower() not in self.internal

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before)

    def _before(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use["name"]
        if not self.outbound(name):
            return
        answer = event.interrupt(INTERRUPT, reason={"tool": name, "input": event.tool_use.get("input") or {}})
        if str(answer).strip().lower() not in {"y", "yes", "approve", "true"}:
            event.cancel_tool = f"The person declined to run {name}. Do not retry it; ask what they want instead."
