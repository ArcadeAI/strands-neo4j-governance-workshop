"""The loan desk agent: a Strands `Agent`, a model, and tools that run through Arcade."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Any

from strands import Agent
from strands.agent import AgentResult
from strands.models.model import Model

from loan_agent.arcade_tools import ArcadeEngine, ArcadeToolbox, Engine
from loan_agent.config import Settings
from loan_agent.local_tools import loan_payment
from loan_agent.models import make_model
from loan_agent.transcript import Transcript

INSTRUCTIONS = resources.files("loan_agent").joinpath("instructions.md").read_text()
NOT_CONNECTED = (
    "\n\nThe loan desk is not connected yet: you have no tools that read or change the loan book. "
    "If asked about loans, say so, and that setting ARCADE_API_KEY connects it."
)


@dataclass
class LoanDesk:
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
) -> LoanDesk:
    """One agent for one person. Pass `model` and `engine` to run it without a provider or Arcade."""
    model = model or make_model(settings)
    if engine is None and settings.arcade_api_key:
        engine = ArcadeEngine.connect(settings.arcade_api_key, settings.arcade_base_url)

    tools: list[Any] = [loan_payment]
    toolbox = None
    if engine is not None:
        toolbox = ArcadeToolbox(
            engine=engine,
            persona=settings.user,
            connected_apps_user=settings.connected_apps_user,
            toolkit=settings.toolkit,
            per_task=settings.tools_per_task,
        )
        tools += toolbox.tools()

    transcript = transcript or Transcript()
    agent = Agent(
        name="loan-desk",
        model=model,
        tools=tools,
        system_prompt=INSTRUCTIONS if toolbox else INSTRUCTIONS + NOT_CONNECTED,
        hooks=[transcript, *hooks],
        session_manager=session_manager,
        callback_handler=None,
        trace_attributes={"loan_desk.user": settings.user},
    )
    return LoanDesk(agent=agent, transcript=transcript, toolbox=toolbox)
