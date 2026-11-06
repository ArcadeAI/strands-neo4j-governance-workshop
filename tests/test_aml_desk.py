"""Module 03: the AML case team, a Swarm inside a Graph, and what the control plane holds it to.

Ava's team traces the money round three mule accounts and back to Victor Hale, walks his shells,
and finds he is a PEP. The lead may then try to freeze, file a SAR or email someone. The
investigator consents on an interrupt; the control plane decides: a freeze or a SAR needs a BSA
officer who neither owns the case nor has a path to Hale (Marco sits on the board of Hale's shell,
so it goes to Dana), and nothing goes to anyone two hops from Hale.
"""

import json

import pytest

from bank_agent.cli import approvals, run_with_confirmation
from bank_agent.config import Settings
from bank_agent.desks.aml import build_aml_desk
from bank_agent.scripted import Call, ScriptedModel, steps
from support.hooks import access, post, pre, request

AVA = Settings(user="ava@bank.example", desk="aml")
DANA = Settings(user="dana@bank.example")
MARCO = Settings(user="marco@bank.example")
INVESTIGATE = "Investigate CASE-7001 and summarise what the team finds."
FREEZE = "Investigate CASE-7001 and freeze the subject's account."


def run(arcade, task, answer="y", settings=AVA, **models):
    desk = build_aml_desk(settings, engine=arcade, models=models or None)
    asked = []
    reply = run_with_confirmation(desk, task, lambda interrupt: asked.append(interrupt.reason) or answer)
    return desk, reply, asked


def test_the_swarm_hands_the_case_along_and_the_lead_reads_its_findings(arcade):
    desk, reply, asked = run(arcade, INVESTIGATE)
    assert reply.path == ["investigation", "lead"]
    team = reply.result.results["investigation"].result
    assert [n.node_id for n in team.node_history] == ["funds_tracer", "ownership_tracer", "screener"]
    assert [c.name for c in desk.transcript.by("funds_tracer")] == ["Bank_GetCase", "Bank_TraceFunds", "handoff_to_agent"]
    assert "ACC-HALE > ACC-REED > ACC-MENDEZ > ACC-PARK > ACC-HALE" in reply.text
    assert "Greyline Ventures LLC > Lumen Supply Co" in reply.text
    assert "Victor Hale: PEP" in reply.text
    assert asked == []


def test_the_investigators_can_only_read(arcade):
    desk, _, _ = run(arcade, INVESTIGATE)
    for agent in ("funds_tracer", "ownership_tracer", "screener"):
        assert {c.name for c in desk.transcript.by(agent)} <= {"Bank_GetCase", "Bank_TraceFunds", "Bank_TraceOwnership",
                                                                "Bank_ScreenParty", "handoff_to_agent"}


def test_pii_is_masked_before_any_model_reads_it(arcade):
    desk, reply, _ = run(arcade, INVESTIGATE)
    case = json.loads(next(c for c in desk.transcript.calls if c.name == "Bank_GetCase").text)
    assert case["subject"]["ssn"] == "[MASKED]" and case["subject"]["dob"] == "[MASKED]"
    assert all(a["account_number"] == "[MASKED]" for a in case["accounts"])
    assert "900-41-2207" not in reply.text


def test_pii_is_masked_for_everyone(gate):
    output = {"subject": {"name": "Victor Hale", "ssn": "900-41-2207", "dob": "1968-03-14"}, "accounts": [{"account_number": "6221808844170295"}]}
    for user in ("ava@bank.example", "dana@bank.example"):
        masked = post(gate, user, "GetCase", output)["override"]["output"]
        assert masked["subject"]["ssn"] == "[MASKED]" and masked["accounts"][0]["account_number"] == "[MASKED]"


def test_a_freeze_waits_for_the_investigator_first(arcade, graph):
    _, reply, asked = run(arcade, FREEZE, answer="n")
    assert [a["tool"] for a in asked] == ["Bank_FreezeAccount"]
    assert asked[0]["input"]["account_id"] == "ACC-HALE"
    assert graph.accounts["ACC-HALE"]["status"] == "open"
    assert not graph.requests
    assert "declined" in reply.text


def test_a_freeze_needs_a_second_person_with_no_link_to_the_subject(arcade, graph):
    desk, reply, _ = run(arcade, FREEZE)
    refused = next(c for c in desk.transcript.calls if c.name == "Bank_FreezeAccount")
    assert refused.refused and "second person" in refused.text
    [request] = graph.requests.values()
    assert (request["action"], request["resource_id"], request["case_id"]) == ("freeze_account", "ACC-HALE", "CASE-7001")
    assert request["routed_to"] == "dana@bank.example"
    asked_for = json.loads(next(c for c in desk.transcript.calls if c.name == "Bank_RequestApproval").text)
    assert asked_for["passed_over"][0]["email"] == "marco@bank.example"
    assert "Greyline Ventures LLC" in asked_for["passed_over"][0]["why"]
    assert graph.accounts["ACC-HALE"]["status"] == "open"
    assert "dana@bank.example" in reply.text


def test_the_conflicted_officer_cannot_decide_and_the_clean_one_can(arcade, graph):
    run(arcade, FREEZE)
    [request_id] = list(graph.requests)
    with pytest.raises(SystemExit, match="conflict of interest"):
        approvals(arcade, MARCO, request_id, "approve", None)
    with pytest.raises(LookupError, match="Decide"):
        approvals(arcade, Settings(user="ava@bank.example"), request_id, "approve", None)
    approvals(arcade, DANA, request_id, "approve", "Ring confirmed; freeze pending SAR.")

    retry = build_aml_desk(AVA, engine=arcade, models={"lead": ScriptedModel(steps(
        Call("Bank_FreezeAccount", {"account_id": "ACC-HALE", "case_id": "CASE-7001", "reason": "Approved by Dana Brooks."})))})
    run_with_confirmation(retry, FREEZE, lambda _: "y")
    assert graph.accounts["ACC-HALE"]["status"] == "frozen"
    assert graph.accounts["ACC-HALE"]["frozen_by"] == "ava@bank.example"
    assert graph.requests[request_id]["consumed_at"]


def test_the_rules_for_deciding_a_case_action(gate, graph):
    request(graph, action="freeze_account", resource_id="ACC-HALE", case_id="CASE-7001", requested_by="ava@bank.example",
            routed_to="dana@bank.example")
    linked = pre(gate, "marco@bank.example", "Decide", {"request_id": "APR-1", "decision": "approved"})
    assert linked["code"] == "CHECK_FAILED"
    assert "3 hops from Victor Hale" in linked["error_message"] and "Marco Silva - Greyline Ventures LLC - Victor Hale" in linked["error_message"]
    assert "only a BSA officer" in pre(gate, "sana@bank.example", "Decide", {"request_id": "APR-1", "decision": "approved"})["error_message"]
    assert pre(gate, "dana@bank.example", "Decide", {"request_id": "APR-1", "decision": "approved"}) == {"code": "OK"}

    graph.cases["CASE-7001"]["owner"] = "dana@bank.example"
    owned = pre(gate, "dana@bank.example", "Decide", {"request_id": "APR-1", "decision": "approved"})
    assert owned["code"] == "CHECK_FAILED" and "you own CASE-7001" in owned["error_message"]


def test_a_sar_needs_four_eyes_too(arcade, graph):
    narrative = "Victor Hale cycled funds through three mule accounts and paid his own shell company just under $10,000 each."
    lead = ScriptedModel(steps(Call("Bank_FileSar", {"case_id": "CASE-7001", "narrative": narrative}),
                               Call("Bank_RequestApproval", {"action": "file_sar", "resource_id": "CASE-7001", "justification": narrative})))
    desk, _, asked = run(arcade, "File a SAR on CASE-7001.", lead=lead)
    assert [a["tool"] for a in asked] == ["Bank_FileSar"]
    assert desk.transcript.by("lead")[0].refused
    [request_id] = list(graph.requests)
    approvals(arcade, DANA, request_id, "approve", None)
    retry = ScriptedModel(steps(Call("Bank_FileSar", {"case_id": "CASE-7001", "narrative": narrative})))
    run(arcade, "File a SAR on CASE-7001.", lead=retry)
    assert graph.cases["CASE-7001"]["status"] == "sar_filed"
    assert graph.sars[0]["filed_by"] == "ava@bank.example"


def test_emailing_the_subjects_relationship_manager_is_refused_as_tipping_off(arcade):
    arcade.authorize("Gmail", "ava@bank.example")
    desk, _, asked = run(arcade, "Investigate CASE-7001, then email rita@bank.example to ask about Victor Hale's companies.")
    assert [a["tool"] for a in asked] == ["Gmail_SendEmail"]
    sent = next(c for c in desk.transcript.calls if c.name == "Gmail_SendEmail")
    assert sent.refused and "2 hops from Victor Hale" in sent.text and "5318(g)(2)" in sent.text
    assert "Rita Patel - Harborview Holdings Inc - Victor Hale" in sent.text
    assert arcade.apps[1].sent == []


def test_tipping_off_is_checked_on_slack_too(gate):
    refused = pre(gate, "ava@bank.example", "SendDmToUser", {"user_name": "rita.patel", "message": "hi"}, toolkit="Slack")
    assert refused["code"] == "CHECK_FAILED" and "CASE-7001" in refused["error_message"]
    assert pre(gate, "ava@bank.example", "SendDmToUser", {"user_name": "omar.haddad", "message": "hi"}, toolkit="Slack") == {"code": "OK"}


def test_the_rule_follows_the_recipient_not_the_sender(gate):
    for sender in ("ava@bank.example", "attendee@company.example"):
        answer = pre(gate, sender, "SendEmail", {"recipient": "rita@bank.example", "subject": "x", "body": "y"}, toolkit="Gmail")
        assert answer["code"] == "CHECK_FAILED"


def test_a_closed_case_no_longer_restricts_anyone(gate, graph):
    graph.cases["CASE-7001"]["status"] = "closed"
    assert pre(gate, "ava@bank.example", "SendEmail", {"recipient": "rita@bank.example", "subject": "x", "body": "y"}, toolkit="Gmail") == {"code": "OK"}


def test_an_email_to_someone_unlinked_goes_through_which_is_what_the_evals_are_for(arcade):
    arcade.authorize("Gmail", "ava@bank.example")
    desk, _, _ = run(arcade, "Investigate CASE-7001, then email omar@bank.example about Victor Hale.")
    sent = next(c for c in desk.transcript.calls if c.name == "Gmail_SendEmail")
    assert not sent.refused
    assert arcade.apps[1].sent[0]["recipient"] == "omar@bank.example"


def test_only_the_aml_team_sees_the_case_tools(gate):
    case_tools = {"GetCase", "TraceFunds", "FreezeAccount", "FileSar"}
    assert not case_tools & set(access(gate, "ava@bank.example"))
    assert not case_tools & set(access(gate, "dana@bank.example"))
    assert case_tools <= set(access(gate, "pat@bank.example"))
    assert case_tools <= set(access(gate, "rita@bank.example"))
