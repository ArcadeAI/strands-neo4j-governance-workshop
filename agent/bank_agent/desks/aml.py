"""The AML case team: a Strands Graph whose first node is a Swarm of investigators, and a lead who acts.

    investigation (Swarm)                                   lead
      funds_tracer ⇄ ownership_tracer ⇄ screener   ──▶     Bank_GetCase, Bank_FreezeAccount, Bank_FileSar,
      (TraceFunds)   (TraceOwnership)   (ScreenParty)       Bank_RequestApproval, arcade_select_tools (Gmail, Slack)

The specialists hand the case to each other with `handoff_to_agent` until the picture is
complete: the money that went round three mule accounts and back, the shell that owns the
beneficiary, the PEP at the top. Then the lead decides what to do about it. The specialists
can only read; only the lead holds tools that act.

Before the lead freezes an account, files a SAR or sends anything outside the team, the run
stops on a Strands interrupt and waits for the investigator (`ConfirmActions`). That is consent.
Authority is the control plane's: a freeze or a SAR always needs a second person, a BSA officer
who neither owns the case nor has a path to the subject in the graph, and an email to anyone two
hops from the subject is refused as tipping off.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from strands.multiagent import GraphBuilder, Swarm
from strands.multiagent.graph import Graph

from bank_agent.arcade_tools import SELECT, Engine
from bank_agent.config import Settings
from bank_agent.confirm import ConfirmActions
from bank_agent.desks.common import Desk, Models, make_agent, model_for, reply_of, toolbox_for
from bank_agent.desks.payments import approval_request
from bank_agent.scripted import Call, Move, Say, find, payload, turn_history
from bank_agent.transcript import Transcript

FUNDS_TOOLS = ("GetCase", "TraceFunds")
OWNERSHIP_TOOLS = ("GetCase", "TraceOwnership")
SCREENER_TOOLS = ("ScreenParty",)
LEAD_TOOLS = ("GetCase", "FreezeAccount", "FileSar", "RequestApproval")
CONFIRM = ("Bank_FreezeAccount", "Bank_FileSar")

FUNDS_PROMPT = """
You are the funds tracer on an AML case team. Read the case with Bank_GetCase, then follow the
money out of the subject's accounts with Bank_TraceFunds. Look for cycles back to the subject and
for many accounts paying one beneficiary. Then hand off to ownership_tracer with what you found
and the subject's party ID.
"""

OWNERSHIP_PROMPT = """
You are the ownership tracer on an AML case team. Walk the ownership graph from the subject with
Bank_TraceOwnership: the companies they own directly and through others, the boards they sit on.
Then hand off to screener with every person and company name worth screening.
"""

SCREENER_PROMPT = """
You are the sanctions and PEP screener on an AML case team. Screen every name you were handed
with Bank_ScreenParty, one call per name. Then summarise the team's findings for the lead: the
money, the ownership, and every list or PEP match. Do not hand off again.
"""

LEAD_PROMPT = """
You lead an AML case team. The investigators' findings are in your input. Decide what the case
needs and do it: freeze an account with Bank_FreezeAccount, file a SAR with Bank_FileSar, or ask
someone for information. A SAR, and the fact that one is being considered, is confidential:
never tell the subject or anyone close to them. Report what you did and what is waiting on whom.
"""


def build_team(funds: Any, ownership: Any, screener: Any) -> Swarm:
    return Swarm(
        [funds, ownership, screener],
        entry_point=funds,
        max_handoffs=6,
        max_iterations=10,
        execution_timeout=600,
        node_timeout=300,
    )


def build_graph(team: Swarm, lead: Any) -> Graph:
    builder = GraphBuilder()
    builder.add_node(team, "investigation")
    builder.add_node(lead, "lead")
    builder.add_edge("investigation", "lead")
    builder.set_entry_point("investigation")
    builder.set_max_node_executions(4)
    builder.set_execution_timeout(900)
    return builder.build()


def build_aml_desk(
    settings: Settings,
    *,
    models: Models = None,
    engine: Engine | None = None,
    hooks: Sequence[Any] = (),
    transcript: Transcript | None = None,
    confirm: Any = None,
) -> Desk:
    """`confirm` is the lead's consent hook; by default it interrupts before a freeze, a SAR or anything outbound."""
    toolbox = toolbox_for(settings, engine)
    transcript = transcript or Transcript()
    confirm = confirm or ConfirmActions(internal=(settings.toolkit,), also=CONFIRM)

    def agent(name: str, tools: Sequence[str], prompt: str, script: Any, extra: Sequence[Any] = (), more: Sequence[Any] = ()) -> Any:
        picked = [*(toolbox.pick(tools) if toolbox else []), *more]
        return make_agent(name, model_for(models, settings, name, script), picked, prompt, transcript, settings, [*hooks, *extra])

    team = build_team(
        agent("funds_tracer", FUNDS_TOOLS, FUNDS_PROMPT, funds_script),
        agent("ownership_tracer", OWNERSHIP_TOOLS, OWNERSHIP_PROMPT, ownership_script),
        agent("screener", SCREENER_TOOLS, SCREENER_PROMPT, screener_script),
    )
    select = [toolbox.select_tool()] if toolbox else []
    lead = agent("lead", LEAD_TOOLS, LEAD_PROMPT, lead_script, extra=[confirm], more=select)
    graph = build_graph(team, lead)
    return Desk(run=lambda task: reply_of(graph(task)), transcript=transcript, toolbox=toolbox, name="aml")


# Default scripts: each investigator does its one job and hands on; the lead acts on what the
# task asks for (freeze, SAR, an email) and follows every refusal to the letter.

CASE = r"\b(CASE-\d+)\b"


def funds_script(messages: Sequence[dict[str, Any]], _tools: list[str]) -> Move:
    history = turn_history(messages)
    case_id = find(messages, CASE)
    if not history:
        return Call("Bank_GetCase", {"case_id": case_id})
    last = history[-1]
    if last.name == "Bank_GetCase":
        case = payload(last) or {}
        accounts = case.get("accounts") or []
        if last.status == "error" or not accounts:
            return Say(f"Could not read {case_id}: {last.text}")
        return Call("Bank_TraceFunds", {"account_id": accounts[0]["account_id"], "hops": 4})
    if last.name == "Bank_TraceFunds":
        case = payload(history[0]) or {}
        trace = payload(last) or {}
        subject = case.get("subject") or {}
        finding = (
            f"Funds from {trace.get('account_id')}: {len(trace.get('cycles', []))} cycle(s) back to the subject "
            f"({'; '.join(' > '.join(c) for c in trace.get('cycles', []))}); accounts reached: {', '.join(trace.get('accounts_reached', []))}."
        )
        return Call("handoff_to_agent", {
            "agent_name": "ownership_tracer",
            "message": f"{finding} Trace the ownership around {subject.get('name')} ({subject.get('party_id')}).",
            "context": {"case_id": case_id, "subject_id": subject.get("party_id")},
        })
    return Say(last.input.get("message", "Handed the case to the ownership tracer."))


def ownership_script(messages: Sequence[dict[str, Any]], _tools: list[str]) -> Move:
    history = turn_history(messages)
    if not history:
        return Call("Bank_TraceOwnership", {"party_id": find(messages, r"\b(P-[A-Z]+)\b")})
    last = history[-1]
    if last.name == "Bank_TraceOwnership":
        found = payload(last) or {}
        names = [found.get("name")] + [r["name"] for r in found.get("owns", [])] + [r["name"] for r in found.get("director_of", [])]
        names = list(dict.fromkeys(n for n in names if n))
        chains = "; ".join(f"{' > '.join(r['chain'])} ({r['effective_pct']}%)" for r in found.get("owns", []))
        return Call("handoff_to_agent", {
            "agent_name": "screener",
            "message": f"Ownership: {chains or 'no companies owned'}. Screen these names: {'; '.join(names)}",
            "context": {"names": names},
        })
    return Say(last.input.get("message", "Handed the names to the screener."))


def screener_script(messages: Sequence[dict[str, Any]], _tools: list[str]) -> Move:
    history = turn_history(messages)
    listed = find(messages, r"Screen these names: ([^\n]+)")
    names = [n.strip() for n in listed.split(";")] if listed else []
    screened = [s for s in history if s.name == "Bank_ScreenParty"]
    if len(screened) < len(names):
        return Call("Bank_ScreenParty", {"name": names[len(screened)]})
    hits = []
    for step in screened:
        result = payload(step) or {}
        hits += [f"{m['name']} on {m['list']} ({m['entry']})" for m in result.get("list_matches", [])]
        hits += [f"{m['name']}: PEP, {m['detail']}" for m in result.get("pep_matches", [])]
    return Say(f"Screening: {'; '.join(hits) or 'no list or PEP matches'}.")


def lead_plan(task: str, case: dict[str, Any], case_id: str) -> list[Call]:
    """What the task asks the lead to do, in order."""
    lowered = task.lower()
    subject = (case.get("subject") or {}).get("name", "the subject")
    accounts = [a["account_id"] for a in case.get("accounts") or []]
    plan: list[Call] = []
    if "freeze" in lowered and accounts:
        plan.append(Call("Bank_FreezeAccount", {"account_id": accounts[0], "case_id": case_id,
                                                "reason": f"Funds cycled through mule accounts back to {subject}; see {case_id}."}))
    if "sar" in lowered.split() or "file a sar" in lowered:
        plan.append(Call("Bank_FileSar", {"case_id": case_id, "narrative": (
            f"{subject} moved funds through three newly opened retail accounts that returned them within days, "
            f"and the same accounts paid a company {subject} controls just under $10,000 each. Details in {case_id}.")}))
    recipient = find([{"content": [{"text": task}]}], r"\b([\w.]+@bank\.example)\b")
    if recipient:
        plan.append(Call(SELECT, {"tasks": ["send an email with Gmail"]}))
        plan.append(Call("Gmail_SendEmail", {"recipient": recipient, "subject": f"Question about {subject}",
                                             "body": f"Can you tell me what you know about {subject}'s accounts and companies?"}))
    return plan


def summary(step) -> str:
    request = payload(step) if step.name == "Bank_RequestApproval" and step.status != "error" else None
    if isinstance(request, dict) and request.get("request_id"):
        return f"- Approval {request['request_id']} for {request['action']} on {request['resource_id']} is waiting on {request['routed_to']}."
    return f"- {step.name}: {' '.join(step.text.split())[:400]}"


def lead_script(messages: Sequence[dict[str, Any]], _tools: list[str]) -> Move:
    history = turn_history(messages)
    case_id = find(messages, CASE)
    task = find(messages, r"Original Task:\s*([^\n]*)") or ""
    if not history:
        return Call("Bank_GetCase", {"case_id": case_id})
    case = payload(history[0]) or {}
    findings = " ".join((find(messages, r"Inputs from previous nodes:([\s\S]*)") or "").split())[:800]
    queue = lead_plan(task, case, case_id)
    for i, step in enumerate(history[1:], start=1):
        if queue and step.name == queue[0].name:
            queue.pop(0)
        if step.status == "error" and "Bank_RequestApproval" in step.text and i == len(history) - 1:
            resource = step.input.get("account_id") or step.input.get("case_id") or case_id
            return approval_request(step.text, resource, f"{task.strip()} {findings}".strip())
    if queue:
        return queue[0]
    done = [summary(step) for step in history[1:]]
    return Say("\n".join([f"Team findings: {findings}" if findings else "", *done]).strip() or f"Nothing to do on {case_id}.")
