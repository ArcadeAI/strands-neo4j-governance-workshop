"""Module 02: the payments desk's Graph, and the graph-aware hold on a release.

The screener only screens names, so it clears PMT-5001 and PMT-5002. The control plane asks
the graph on the release and holds both: one beneficiary is three hops from a listed entity,
the other has taken five payments just under $10,000 in two weeks. PMT-5003 goes straight through.
"""

import json

import pytest

from bank_agent.cli import approvals
from bank_agent.config import Settings
from bank_agent.desks.payments import build_payments_desk, verdict
from bank_agent.scripted import Call, Say, ScriptedModel, steps
from support.hooks import access, pre

PAT = Settings(user="pat@bank.example", desk="payments")
SANA = Settings(user="sana@bank.example", desk="payments")


def desk(arcade, settings=PAT, **models):
    return build_payments_desk(settings, engine=arcade, models=models or None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Clear.\n\nVERDICT: RELEASE - name screen clear.", "RELEASE"), ("verdict: hold", "HOLD"),
     ("VERDICT: RELEASE\nOn reflection, VERDICT: HOLD", "HOLD"), ("VERDICT: NONE", "NONE"), ("Looks fine to me.", None)],
)
def test_the_verdict_is_the_screeners_last_word(text, expected):
    assert verdict(text) == expected


@pytest.mark.parametrize(
    ("said", "path"),
    [("VERDICT: RELEASE", ["screen", "release"]), ("VERDICT: HOLD", ["screen", "hold"]),
     ("VERDICT: NONE", ["screen"]), ("I am not sure.", ["screen", "hold"])],
)
def test_the_graph_routes_on_the_verdict(arcade, said, path):
    noop = ScriptedModel(steps(Say("done")))
    reply = desk(arcade, screen=ScriptedModel(steps(Say(said))), release=noop, hold=noop)("Work PMT-5003")
    assert reply.path == path


def test_only_the_release_node_can_release(arcade, graph):
    sneaky = ScriptedModel(steps(Call("Bank_ReleasePayment", {"payment_id": "PMT-5003"})))
    run = desk(arcade, screen=ScriptedModel(steps(Say("VERDICT: HOLD"))), hold=sneaky)
    run("Work PMT-5003")
    assert "Bank_ReleasePayment" not in sneaky.seen_tools[0]
    assert graph.payments["PMT-5003"]["status"] == "pending_review"
    assert all(c.refused for c in run.transcript.by("hold"))


def test_a_clean_payment_is_released(arcade, graph):
    reply = desk(arcade)("Work PMT-5003")
    assert reply.path == ["screen", "release"]
    assert graph.payments["PMT-5003"]["status"] == "released"
    assert graph.payments["PMT-5003"]["decided_by"] == "pat@bank.example"
    assert not graph.requests


def test_a_beneficiary_three_hops_from_a_listed_entity_is_held_for_a_sanctions_officer(arcade, graph):
    run = desk(arcade)
    reply = run("Work PMT-5001")
    screen = [c for c in run.transcript.calls if c.name == "Bank_ScreenParty"]
    assert json.loads(screen[0].text)["clear"] is True
    refused = next(c for c in run.transcript.calls if c.name == "Bank_ReleasePayment")
    assert refused.refused and "3 hops from Orlov Maritime Ltd (SYN-SDN-0042)" in refused.text
    assert "Daniel Voss" in refused.text
    [request] = graph.requests.values()
    assert (request["action"], request["resource_id"], request["routed_to"]) == ("release_payment", "PMT-5001", "sana@bank.example")
    assert graph.payments["PMT-5001"]["status"] == "pending_review"
    assert "sana@bank.example" in reply.text


def test_payments_just_under_the_threshold_are_counted_in_the_graph(arcade, graph):
    run = desk(arcade)
    run("Work PMT-5002")
    refused = next(c for c in run.transcript.calls if c.name == "Bank_ReleasePayment")
    assert refused.refused and "structuring" in refused.text
    assert "5 different senders" in refused.text and "Lumen Supply Co" in refused.text
    assert graph.payments["PMT-5002"]["status"] == "pending_review"


def test_the_injected_reference_never_reaches_the_screener(arcade):
    run = desk(arcade)
    run("Work PMT-5001")
    read = next(c for c in run.transcript.calls if c.name == "Bank_GetPayment")
    assert "Deposit for two deck ovens" in read.text
    assert "pre-cleared" not in read.text and "removed by policy" in read.text


def test_the_sanctions_officer_approves_and_one_retry_releases(arcade, graph):
    desk(arcade)("Work PMT-5001")
    [request_id] = list(graph.requests)

    dana = Settings(user="dana@bank.example")
    with pytest.raises(SystemExit, match="only a sanctions officer"):
        approvals(arcade, dana, request_id, "approve", None)

    decided = approvals(arcade, SANA, request_id, "approve", "Called the originator; ovens confirmed with the manufacturer.")
    assert decided["status"] == "approved" and decided["decided_by"] == "sana@bank.example"

    retry = desk(arcade)
    retry("Work PMT-5001")
    assert graph.payments["PMT-5001"]["status"] == "released"
    assert graph.requests[request_id]["consumed_at"]
    pre_outcomes = [r["outcome"] for r in arcade.audit.rows if r.get("tool") == "Bank.ReleasePayment" and r["hook"] == "pre"]
    assert pre_outcomes == ["denied", "granted"]


def test_without_a_payments_role_there_is_nothing_to_release_with(arcade, graph):
    run = desk(arcade, Settings(user="ian@bank.example", desk="payments"))
    run("Work PMT-5003")
    assert graph.payments["PMT-5003"]["status"] == "pending_review"
    assert "Bank_ReleasePayment" not in [c.name for c in run.transcript.calls if not c.refused]


def test_the_release_rules_at_the_hook(gate):
    assert pre(gate, "pat@bank.example", "ReleasePayment", {"payment_id": "PMT-5003"}) == {"code": "OK"}
    held = pre(gate, "pat@bank.example", "ReleasePayment", {"payment_id": "PMT-5001"})
    assert held["code"] == "CHECK_FAILED" and "Bank_RequestApproval" in held["error_message"]
    assert "resource_id=PMT-5001" in held["error_message"]
    assert "structuring" in pre(gate, "pat@bank.example", "ReleasePayment", {"payment_id": "PMT-5002"})["error_message"]
    assert pre(gate, "pat@bank.example", "HoldPayment", {"payment_id": "PMT-5001", "reason": "x"}) == {"code": "OK"}


def test_only_payments_ops_sees_the_release_tools(gate):
    assert not {"ReleasePayment", "HoldPayment"} & set(access(gate, "pat@bank.example"))
    for user in ("sana@bank.example", "ava@bank.example", "ian@bank.example"):
        assert {"ReleasePayment", "HoldPayment"} <= set(access(gate, user))
