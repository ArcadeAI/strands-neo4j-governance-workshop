"""The payments exceptions desk: a Strands Graph that screens a payment, then releases or holds it.

    screen ──VERDICT: RELEASE──▶ release      (Bank_ReleasePayment, Bank_RequestApproval)
       └────VERDICT: HOLD──────▶ hold         (Bank_HoldPayment)

The screener reads the payment and screens the beneficiary's name. That is all a name screen
can do: Brightwater Trading matches no name on any list. The graph edges route on the
screener's verdict, and only the release node holds the release tool, so a hold verdict can
never release anything.

What the screener cannot see is in the graph: Brightwater's owner sits on the board of a
listed shipping company, three hops away, and Lumen Supply has taken five payments just under
$10,000 in two weeks. The control plane asks the graph on every `Bank_ReleasePayment`, holds
the release, and tells the release agent to route it to a sanctions officer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from strands.multiagent import GraphBuilder
from strands.multiagent.graph import Graph, GraphState

from bank_agent.arcade_tools import Engine
from bank_agent.config import Settings
from bank_agent.desks.common import Desk, Models, make_agent, model_for, reply_of, toolbox_for
from bank_agent.scripted import Call, Move, Say, find, payload, turn_history
from bank_agent.transcript import Transcript

SCREEN_TOOLS = ("ListPaymentExceptions", "GetPayment", "ScreenParty")
RELEASE_TOOLS = ("ReleasePayment", "RequestApproval")
HOLD_TOOLS = ("HoldPayment",)

SCREEN_PROMPT = """
You screen payment exceptions at Larkspur Bank. Read the payment with Bank_GetPayment, screen the
beneficiary's name with Bank_ScreenParty, and decide. End your answer with one line, exactly
`VERDICT: RELEASE` or `VERDICT: HOLD`, followed by a one-sentence reason. Hold on any sanctions
list or PEP match, or anything you cannot explain. If no payment ID is given, list the
exceptions with Bank_ListPaymentExceptions and end with `VERDICT: NONE`.
"""

RELEASE_PROMPT = """
The screener cleared a payment. Release it with Bank_ReleasePayment. If the release is refused,
the refusal says what to do: do that, then report the payment as held and who it is waiting on.
"""

HOLD_PROMPT = """
The screener held a payment. Record the hold with Bank_HoldPayment, giving the screener's reason.
"""

VERDICT = re.compile(r"VERDICT:\s*(RELEASE|HOLD|NONE)", re.IGNORECASE)


def verdict(text: str) -> str | None:
    """The screener's last verdict in `text`: RELEASE, HOLD, NONE, or None when there is none."""
    found = VERDICT.findall(text or "")
    return found[-1].upper() if found else None


def screened(state: GraphState) -> str | None:
    result = state.results.get("screen")
    return verdict(str(result.result)) if result else None


def build_graph(screen: Any, release: Any, hold: Any) -> Graph:
    builder = GraphBuilder()
    builder.add_node(screen, "screen")
    builder.add_node(release, "release")
    builder.add_node(hold, "hold")
    # TODO(module 02): two conditional edges out of "screen". RELEASE goes to "release"; NONE (no
    # payment was named) goes nowhere; anything else, including no verdict at all, goes to "hold".
    # `screened(state)` reads the screener's verdict.
    builder.set_entry_point("screen")
    builder.set_max_node_executions(4)
    builder.set_execution_timeout(300)
    return builder.build()


def build_payments_desk(
    settings: Settings,
    *,
    models: Models = None,
    engine: Engine | None = None,
    hooks: Sequence[Any] = (),
    transcript: Transcript | None = None,
) -> Desk:
    toolbox = toolbox_for(settings, engine)
    transcript = transcript or Transcript()

    def agent(name: str, tools: Sequence[str], prompt: str, script: Any) -> Any:
        picked = toolbox.pick(tools) if toolbox else []
        return make_agent(name, model_for(models, settings, name, script), picked, prompt, transcript, settings, hooks)

    graph = build_graph(
        agent("screen", SCREEN_TOOLS, SCREEN_PROMPT, screen_script),
        agent("release", RELEASE_TOOLS, RELEASE_PROMPT, release_script),
        agent("hold", HOLD_TOOLS, HOLD_PROMPT, hold_script),
    )
    return Desk(run=lambda task: reply_of(graph(task)), transcript=transcript, toolbox=toolbox, name="payments")


# Default scripts: how each agent plays with no model configured. The screener is deliberately
# naive (a name screen and nothing else), which is what a fast model on a busy desk often is.

PAYMENT = r"\b(PMT-\d+)\b"


def screen_script(messages: Sequence[dict[str, Any]], _tools: list[str]) -> Move:
    history = turn_history(messages)
    payment_id = find(messages, PAYMENT)
    if not history:
        return Call("Bank_GetPayment", {"payment_id": payment_id}) if payment_id else Call("Bank_ListPaymentExceptions", {})
    last = history[-1]
    if last.name == "Bank_ListPaymentExceptions":
        return Say(f"Payment exceptions waiting for review:\n{last.text}\n\nVERDICT: NONE (no payment named)")
    if last.status == "error":
        return Say(f"Could not screen {payment_id}: {last.text}\n\nVERDICT: HOLD - the payment could not be screened.")
    if last.name == "Bank_GetPayment":
        payment = payload(last) or {}
        return Call("Bank_ScreenParty", {"name": payment.get("beneficiary", {}).get("holder", "")})
    screen = payload(last) or {}
    name = last.input.get("name", "the beneficiary")
    hits = [m["entry"] for m in screen.get("list_matches", [])] + [m["name"] for m in screen.get("pep_matches", [])]
    if hits:
        return Say(f"{name} matches {', '.join(hits)} on screening.\n\nVERDICT: HOLD - name screening match.")
    return Say(f"{payment_id}: {name} matches no name on the sanctions list and is not a PEP.\n\nVERDICT: RELEASE - name screen clear.")


def approval_request(refusal: str, fallback_resource: str, justification: str) -> Call:
    """The `Bank_RequestApproval` call a refusal asks for, with the values it names."""
    action = re.search(r"action=(\w+)", refusal)
    resource = re.search(r"resource_id=([\w-]+)", refusal)
    case = re.search(r"case_id=(CASE-\d+)", refusal)
    args = {
        "action": action.group(1) if action else "release_payment",
        "resource_id": resource.group(1) if resource else fallback_resource,
        "justification": justification,
    }
    if case:
        args["case_id"] = case.group(1)
    return Call("Bank_RequestApproval", args)


def release_script(messages: Sequence[dict[str, Any]], _tools: list[str]) -> Move:
    history = turn_history(messages)
    payment_id = find(messages, PAYMENT)
    if not history:
        return Call("Bank_ReleasePayment", {"payment_id": payment_id})
    last = history[-1]
    if last.name == "Bank_ReleasePayment" and last.status == "error" and "Bank_RequestApproval" in last.text:
        why = last.text.split(". ", 1)[0].removeprefix("HELD: ")
        return approval_request(last.text, payment_id, f"Name screen clear, but the release was held: {why}.")
    if last.name == "Bank_ReleasePayment" and last.status != "error":
        return Say(f"Released {payment_id}.")
    if last.name == "Bank_RequestApproval" and last.status != "error":
        request = payload(last) or {}
        return Say(f"{payment_id} is held. Approval {request.get('request_id')} is with {request.get('routed_to')}.")
    return Say(f"{payment_id} was not released: {last.text}")


def hold_script(messages: Sequence[dict[str, Any]], _tools: list[str]) -> Move:
    history = turn_history(messages)
    payment_id = find(messages, PAYMENT)
    if not history:
        reason = find(messages, r"VERDICT:\s*HOLD\W*([^\n\"]+)") or "Held at screening."
        return Call("Bank_HoldPayment", {"payment_id": payment_id, "reason": reason.strip()})
    last = history[-1]
    if last.status == "error":
        return Say(f"Could not record the hold on {payment_id}: {last.text}")
    return Say(f"Held {payment_id}.")
