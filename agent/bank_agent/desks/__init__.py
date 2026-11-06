"""Bowser Capital's desks, each a different Strands multi-agent pattern over the same governed tools.

- payments: a Graph with conditional edges (screen, then release or hold)
- aml: a Graph whose first node is a Swarm of investigators, and a lead who acts, with interrupts
- banker: a coordinator whose tools are agents (agents as tools)
"""

from __future__ import annotations

from collections.abc import Callable

from bank_agent.desks.common import Desk, Reply


def builder(desk: str) -> Callable[..., Desk]:
    if desk == "payments":
        from bank_agent.desks.payments import build_payments_desk

        return build_payments_desk
    if desk == "aml":
        from bank_agent.desks.aml import build_aml_desk

        return build_aml_desk
    if desk == "banker":
        from bank_agent.desks.banker import build_banker_desk

        return build_banker_desk
    raise ValueError(f"no desk {desk!r}")


__all__ = ["Desk", "Reply", "builder"]
