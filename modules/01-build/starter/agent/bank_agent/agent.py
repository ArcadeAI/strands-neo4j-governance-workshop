"""Larkspur Bank's assistant: one Strands `Agent`, a model, and tools that run through Arcade.

This is module 01. Every desk after it (payments, AML, banker) is built from the same parts:
a model from `make_model`, the Bank tools Arcade lists for one employee, and the transcript hook.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Any

from strands import Agent
from strands.agent import AgentResult
from strands.models.model import Model

from bank_agent.arcade_tools import ArcadeToolbox, Engine
from bank_agent.config import Settings
from bank_agent.desks.common import toolbox_for
from bank_agent.local_tools import fx_convert  # noqa: F401
from bank_agent.models import make_model
from bank_agent.transcript import Transcript

INSTRUCTIONS = resources.files("bank_agent").joinpath("instructions.md").read_text()
NOT_CONNECTED = (
    "\n\nThe bank is not connected yet: you have no tools that read or change payments, cases or deals. "
    "If asked about them, say so, and that setting ARCADE_API_KEY connects it."
)


@dataclass
class Assistant:
    agent: Agent
    transcript: Transcript
    toolbox: ArcadeToolbox | None

    def __call__(self, prompt: Any) -> AgentResult:
        return self.agent(prompt)

    @property
    def links(self) -> list[str]:
        return self.toolbox.links if self.toolbox else []


def build_agent(
    settings: Settings,
    *,
    model: Model | None = None,
    engine: Engine | None = None,
    hooks: Sequence[Any] = (),
    session_manager: Any = None,
    transcript: Transcript | None = None,
) -> Assistant:
    """One agent for one employee. Pass `model` and `engine` to run it without a provider or Arcade."""
    model = model or make_model(settings)
    toolbox = toolbox_for(settings, engine)

    # TODO(module 01): give the agent fx_convert, and, when the toolbox is connected, every tool it
    # lists for this employee (toolbox.tools()).
    tools: list[Any] = []

    transcript = transcript or Transcript()
    agent = Agent(
        name="assistant",
        model=model,
        tools=tools,
        system_prompt=INSTRUCTIONS if toolbox else INSTRUCTIONS + NOT_CONNECTED,
        hooks=[transcript, *hooks],
        session_manager=session_manager,
        callback_handler=None,
        trace_attributes={"bank.user": settings.user, "bank.desk": "assistant"},
    )
    return Assistant(agent=agent, transcript=transcript, toolbox=toolbox)
