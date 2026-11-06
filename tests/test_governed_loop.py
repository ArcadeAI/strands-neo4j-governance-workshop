"""The whole workshop story, end to end, with a scripted model, the fake Arcade, the real hooks and tools.

Alice asks for an approval above her authority. The control plane refuses and says what to do;
she escalates; the request lands with Charlie; she cannot approve it herself; Charlie approves
it outside the agent; her retry goes through once, and only once.
"""

import json

from loan_agent.agent import build_agent
from loan_agent.cli import approvals
from loan_agent.config import Settings
from loan_agent.scripted import Call, ScriptedModel, steps

ALICE = Settings(user="alice@bank.example")
BOB = Settings(user="bob@bank.example")
CHARLIE = Settings(user="charlie@bank.example")
APPROVE = Call("LoanDesk_ApproveLoan", {"loan_id": "LN-2291", "amount": 95000})


def escalate(history):
    refusal = history[-1].text
    assert "LoanDesk_RequestApproval" in refusal
    return Call("LoanDesk_RequestApproval", {"action": "approve_loan", "resource_id": "LN-2291", "amount": 95000,
                                             "justification": "DSCR 1.4x, collateral appraised."})


def ask(arcade, settings, *moves, prompt="go"):
    desk = build_agent(settings, model=ScriptedModel(steps(*moves)), engine=arcade)
    result = desk(prompt)
    return desk, str(result)


def test_the_governed_loop(arcade, graph):
    desk, _ = ask(arcade, ALICE, APPROVE, escalate)
    refused, requested = desk.transcript.calls
    assert refused.refused and "exceeds your approval authority of 50000" in refused.text
    request = json.loads(requested.text)
    assert request["routed_to"] == "charlie@bank.example"
    assert graph.loans["LN-2291"]["status"] == "pending"

    desk, _ = ask(arcade, ALICE, Call("LoanDesk_Decide", {"request_id": request["request_id"], "decision": "approved"}))
    assert desk.transcript.calls[0].refused and "you asked for" in desk.transcript.calls[0].text

    decided = approvals(arcade, CHARLIE, request["request_id"], "approve", "Collateral checks out.")
    assert decided["status"] == "approved" and decided["decided_by"] == "charlie@bank.example"

    desk, _ = ask(arcade, ALICE, APPROVE)
    assert not desk.transcript.calls[0].refused
    assert graph.loans["LN-2291"]["status"] == "approved"
    assert graph.loans["LN-2291"]["decisions"][-1]["decided_by"] == "alice@bank.example"
    assert [r["outcome"] for r in arcade.audit.recent() if r.get("tool") == "LoanDesk.ApproveLoan" and r["hook"] == "pre"] == ["denied", "granted"]


def test_a_grant_is_spent_by_the_first_retry(arcade, graph):
    graph.loans["LN-2290"]["status"] = "pending"
    ask(arcade, ALICE, Call("LoanDesk_RequestApproval", {"action": "approve_loan", "resource_id": "LN-2290", "amount": 240000, "justification": "x"}))
    [request_id] = list(graph.requests)
    approvals(arcade, CHARLIE, request_id, "approve", None)
    first, _ = ask(arcade, ALICE, Call("LoanDesk_ApproveLoan", {"loan_id": "LN-2290", "amount": 240000}))
    assert not first.transcript.calls[0].refused
    graph.loans["LN-2290"]["status"] = "pending"
    second, _ = ask(arcade, ALICE, Call("LoanDesk_ApproveLoan", {"loan_id": "LN-2290", "amount": 240000}))
    assert second.transcript.calls[0].refused


def test_a_shaved_amount_does_not_use_the_grant(arcade, graph):
    ask(arcade, ALICE, APPROVE, escalate)
    [request_id] = list(graph.requests)
    approvals(arcade, CHARLIE, request_id, "approve", None)
    desk, _ = ask(arcade, ALICE, Call("LoanDesk_ApproveLoan", {"loan_id": "LN-2291", "amount": 95001}))
    assert desk.transcript.calls[0].refused
    assert graph.requests[request_id]["consumed_at"] is None


def test_an_analyst_is_never_offered_the_decision_tools(arcade):
    desk = build_agent(BOB, model=ScriptedModel(), engine=arcade)
    desk("hi")
    offered = desk.agent.model.seen_tools[0]
    assert "LoanDesk_SearchLoans" in offered
    assert not {"LoanDesk_ApproveLoan", "LoanDesk_DenyLoan", "LoanDesk_Decide"} & set(offered)


def test_a_hidden_tool_is_refused_even_if_called_directly(arcade):
    from loan_agent.arcade_tools import ArcadeToolDef

    outcome = arcade.execute(ArcadeToolDef("LoanDesk.ApproveLoan", "LoanDesk", version="1.0.0"), {"loan_id": "LN-2292", "amount": 1}, "bob@bank.example")
    assert outcome.error and "not available" in outcome.error


def test_redaction_depends_on_who_is_asking(arcade):
    alice, _ = ask(arcade, ALICE, Call("LoanDesk_GetLoan", {"loan_id": "LN-2291"}))
    charlie, _ = ask(arcade, CHARLIE, Call("LoanDesk_GetLoan", {"loan_id": "LN-2291"}))
    assert json.loads(alice.transcript.calls[0].text)["tax_id"] == "[REDACTED]"
    assert json.loads(charlie.transcript.calls[0].text)["tax_id"] == "47-3389012"


def test_the_injected_instruction_never_reaches_the_model(arcade, graph):
    desk, _ = ask(arcade, ALICE, Call("LoanDesk_GetLoan", {"loan_id": "LN-2291"}))
    notes = json.loads(desk.transcript.calls[0].text)["underwriter_notes"]
    original = graph.loans["LN-2291"]["underwriter_notes"]
    assert notes != original and "removed by policy" in notes
    assert notes.split("\n\n")[0] == original.split("\n\n")[0]


def test_a_small_loan_in_a_big_group_is_escalated(arcade):
    desk, _ = ask(arcade, ALICE, Call("LoanDesk_GetBorrowerNetwork", {"loan_id": "LN-2297"}),
                  Call("LoanDesk_ApproveLoan", {"loan_id": "LN-2297", "amount": 32000}))
    network, refused = desk.transcript.calls
    assert json.loads(network.text)["group_exposure"]["approved"] == 47500
    assert refused.refused and "ownership group" in refused.text


def test_raising_clearance_in_the_graph_changes_the_answer(arcade, graph):
    graph.officers["alice@bank.example"]["clearance"] = 250000
    desk, _ = ask(arcade, ALICE, Call("LoanDesk_ApproveLoan", {"loan_id": "LN-2299", "amount": 88000}))
    assert not desk.transcript.calls[0].refused
    assert graph.loans["LN-2299"]["status"] == "approved"


def test_bob_cannot_decide_from_the_cli(arcade, graph):
    ask(arcade, ALICE, APPROVE, escalate)
    [request_id] = list(graph.requests)
    try:
        approvals(arcade, BOB, request_id, "approve", None)
    except LookupError as exc:
        assert "hides it" in str(exc)
    else:
        raise AssertionError("bob decided a request")


def test_charlie_sees_what_is_waiting_on_him(arcade):
    ask(arcade, ALICE, APPROVE, escalate)
    pending = approvals(arcade, CHARLIE, None, None, None)
    assert pending["count"] == 1 and pending["requests"][0]["requested_by"] == "alice@bank.example"
