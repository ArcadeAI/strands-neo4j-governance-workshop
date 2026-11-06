"""The banker copilot: a coordinator agent whose tools are other agents, behind an information barrier.

    coordinator ── company_research (agent: Bank_SearchCompanies, Bank_GetCompanyProfile)
                ── deal_desk        (agent: Bank_ListDeals, Bank_GetDeal), only if Arcade lists them
                ── Bank_RequestApproval

Each specialist is wrapped with `Agent.as_tool`, so the coordinator calls it like any tool and
gets back its answer, not its tool calls. Which specialists exist is decided by what Arcade
lists for the banker: the access hook hides the deal tools from anyone who is over the wall for
no deal, so a public-side banker's coordinator has no deal desk to call at all.

What leaks through a company profile is handled after the call: the post hook masks every deal
record the banker is not over the wall for. When the control room approves a wall-crossing, the
graph gets a WALL_CROSSED edge with an expiry; until then the deal is restricted, and after it
the deal is restricted again, with nobody having to remember to revoke anything.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from bank_agent.arcade_tools import Engine
from bank_agent.config import Settings
from bank_agent.desks.common import Desk, Models, Reply, make_agent, model_for, toolbox_for
from bank_agent.scripted import Call, Move, Say, find, payload, turn_history
from bank_agent.transcript import Transcript

RESEARCH_TOOLS = ("SearchCompanies", "GetCompanyProfile")
DEAL_TOOLS = ("ListDeals", "GetDeal")
COORDINATOR_TOOLS = ("RequestApproval",)

RESEARCH_PROMPT = """
You research companies for a banker at Larkspur Bank. Find the company with Bank_SearchCompanies
and read its profile with Bank_GetCompanyProfile. Answer with what the profile says. Fields
marked restricted are behind the information barrier: say they are restricted, never guess them.
"""

DEAL_PROMPT = """
You answer questions about the M&A deals the banker is cleared for, with Bank_ListDeals and
Bank_GetDeal. Answer only from what the tools return.
"""

COORDINATOR_PROMPT = """
You are a banker's copilot at Larkspur Bank. Use company_research for anything about a company.
Use deal_desk, if you have it, for deal questions. If a deal is restricted and the banker needs
it for their work, ask the control room with Bank_RequestApproval (action cross_wall, the deal
ID, and why), then stop. Never guess what is behind the information barrier.
"""


def build_banker_desk(
    settings: Settings,
    *,
    models: Models = None,
    engine: Engine | None = None,
    hooks: Sequence[Any] = (),
    transcript: Transcript | None = None,
) -> Desk:
    toolbox = toolbox_for(settings, engine)
    transcript = transcript or Transcript()

    def agent(name: str, tools: Sequence[Any], prompt: str, script: Any, description: str | None = None) -> Any:
        return make_agent(name, model_for(models, settings, name, script), tools, prompt, transcript, settings, hooks, description)

    def listed(names: Sequence[str]) -> list[Any]:
        return toolbox.pick(names) if toolbox else []

    specialists = []
    research_tools = listed(RESEARCH_TOOLS)
    if research_tools:
        research = agent("company_research", research_tools, RESEARCH_PROMPT, research_script)
        specialists.append(research.as_tool(
            name="company_research",
            description="Research one company: who it is, who covers it, who owns it, and any deals it is part of. Input: the question, naming the company.",
        ))
    deal_tools = listed(DEAL_TOOLS)
    if deal_tools:
        deals = agent("deal_desk", deal_tools, DEAL_PROMPT, deal_script)
        specialists.append(deals.as_tool(
            name="deal_desk",
            description="Answer a question about an M&A deal you are cleared for. Input: the question, naming the deal ID if known.",
        ))

    coordinator = agent("coordinator", [*specialists, *listed(COORDINATOR_TOOLS)], COORDINATOR_PROMPT, coordinator_script)

    def run(task: Any) -> Reply:
        result = coordinator(task)
        return Reply(text=str(result).strip(), stop_reason=result.stop_reason, interrupts=list(result.interrupts or []),
                     path=["coordinator"], result=result)

    return Desk(run=run, transcript=transcript, toolbox=toolbox, name="banker")


# Default scripts.

DEAL = r"\b(DL-[A-Z]+)\b"
NOT_A_COMPANY = {
    "A", "Any", "Are", "Ask", "Brief", "Bring", "Can", "Cross", "Do", "Find", "Get", "Give", "How", "I", "Is", "Me", "My",
    "Please", "Prep", "Project", "Request", "Show", "Tell", "The", "What", "Which", "Who", "Why",
}


def company_in(text: str) -> str:
    """The first capitalized word that is not a sentence opener: a scripted model's guess at the company named."""
    for word in re.findall(r"\b[A-Z][a-z]+\b", text):
        if word not in NOT_A_COMPANY:
            return word
    return text.strip()


def wants_deal(task: str) -> bool:
    return bool(re.search(r"\b(deal|deals|project|acquisition|m&a|DL-[A-Z]+)\b", task, re.IGNORECASE))


def wants_crossing(task: str) -> bool:
    return bool(re.search(r"\b(cross|crossing|over the wall|wall-crossing|need access)\b", task, re.IGNORECASE))


def research_script(messages: Sequence[dict[str, Any]], _tools: list[str]) -> Move:
    history = turn_history(messages)
    if not history:
        prompt = next((b["text"] for m in messages for b in m.get("content", []) if "text" in b), "")
        return Call("Bank_SearchCompanies", {"query": company_in(prompt)})
    last = history[-1]
    if last.name == "Bank_SearchCompanies":
        found = (payload(last) or {}).get("companies") or []
        if last.status == "error" or not found:
            return Say(f"No company found for {last.input.get('query')!r}.")
        return Call("Bank_GetCompanyProfile", {"company_id": found[0]["company_id"]})
    return Say(last.text)


def deal_script(messages: Sequence[dict[str, Any]], _tools: list[str]) -> Move:
    history = turn_history(messages)
    deal_id = find(messages, DEAL)
    if not history:
        return Call("Bank_GetDeal", {"deal_id": deal_id}) if deal_id else Call("Bank_ListDeals", {})
    return Say(history[-1].text)


def coordinator_script(messages: Sequence[dict[str, Any]], tools: list[str]) -> Move:
    history = turn_history(messages)
    task = next((b["text"] for m in reversed(messages) if m.get("role") == "user"
                 for b in m.get("content", []) if "text" in b), "")
    if not history:
        if "company_research" in tools:
            return Call("company_research", {"input": task})
        return Say("I have no research tools for you: Arcade lists none of the banker tools for your role.")
    names = [s.name for s in history]
    deal_id = find(messages, DEAL)
    restricted = any("RESTRICTED" in s.text for s in history)
    if wants_crossing(task) and restricted and deal_id and "Bank_RequestApproval" not in names and "Bank_RequestApproval" in tools:
        return Call("Bank_RequestApproval", {"action": "cross_wall", "resource_id": deal_id,
                                             "justification": f"Banker request: {task.strip()}"})
    if wants_deal(task) and "deal_desk" in tools and "deal_desk" not in names:
        return Call("deal_desk", {"input": f"{task} {deal_id or ''}".strip()})
    return Say("\n\n".join(f"{s.name}: {s.text}" for s in history))
