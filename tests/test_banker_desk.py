"""Module 04: the banker copilot, agents as tools, behind an information barrier kept in the graph.

Ian covers Lakeside Bakehouse from the public side. Mia, on the private side, is advising
Northwind on buying it (Project Falcon). Ian's coordinator has no deal desk to call, and the
company profile it reads has Falcon masked. When the control room approves a crossing, the graph
gets a WALL_CROSSED edge that expires on its own, and only Falcon opens: Heron stays masked.
"""

from datetime import UTC, datetime, timedelta

import pytest

from bank_agent.cli import approvals
from bank_agent.config import Settings
from bank_agent.desks.banker import build_banker_desk, company_in
from bank_agent.scripted import Call, ScriptedModel, steps
from support.hooks import access, post, pre

IAN = Settings(user="ian@bank.example", desk="banker")
MIA = Settings(user="mia@bank.example", desk="banker")
CORA = Settings(user="cora@bank.example")
RESTRICTED = "[RESTRICTED: information barrier]"
BRIEF = "Brief me on Lakeside Bakehouse and any deal it is part of."


def desk(arcade, settings=IAN, **models):
    return build_banker_desk(settings, engine=arcade, models=models or None)


def coordinator_tools(arcade, settings):
    model = ScriptedModel(steps())
    desk(arcade, settings, coordinator=model)("hello")
    return model.seen_tools[0]


def test_the_scripted_researcher_finds_the_company_named():
    assert company_in("Brief me on Lakeside Bakehouse before my call") == "Lakeside"
    assert company_in("What does Kestrel do?") == "Kestrel"


def test_the_deal_desk_only_exists_for_someone_over_the_wall(arcade):
    assert coordinator_tools(arcade, IAN) == ["company_research", "Bank_RequestApproval"]
    assert coordinator_tools(arcade, MIA) == ["company_research", "deal_desk", "Bank_RequestApproval"]


def test_the_coordinator_calls_agents_and_gets_their_answers(arcade):
    run = desk(arcade, MIA)
    reply = run(BRIEF)
    assert [c.agent for c in run.transcript.calls] == ["company_research", "company_research", "coordinator", "deal_desk", "coordinator"]
    assert "Project Falcon" in reply.text and "Northwind Bakery LLC" in reply.text


def test_a_public_side_banker_gets_the_profile_with_the_deal_masked(arcade):
    run = desk(arcade)
    reply = run(BRIEF)
    assert "Lakeside Bakehouse LLC" in reply.text and "Grace Lin" in reply.text
    assert RESTRICTED in reply.text and "DL-FALCON" in reply.text
    for secret in ("Project Falcon", "Northwind", "14500000", "Exclusivity"):
        assert secret not in reply.text


def test_reading_a_deal_from_across_the_wall_is_refused_with_the_way_over(gate):
    refused = pre(gate, "ian@bank.example", "GetDeal", {"deal_id": "DL-FALCON"})
    assert refused["code"] == "CHECK_FAILED"
    assert "action=cross_wall" in refused["error_message"] and "resource_id=DL-FALCON" in refused["error_message"]
    assert pre(gate, "mia@bank.example", "GetDeal", {"deal_id": "DL-FALCON"}) == {"code": "OK"}


def test_the_deal_tools_are_hidden_from_anyone_over_the_wall_for_nothing(gate):
    for user in ("ian@bank.example", "cora@bank.example", "pat@bank.example"):
        assert {"ListDeals", "GetDeal"} <= set(access(gate, user))
    assert not {"ListDeals", "GetDeal"} & set(access(gate, "mia@bank.example"))


def test_masking_is_per_deal_record(gate, graph):
    graph.crossings.append({"email": "ian@bank.example", "deal_id": "DL-FALCON", "expires_at": "2999-01-01T00:00:00Z"})
    output = {"count": 2, "deals": [{"deal_id": "DL-FALCON", "codename": "Project Falcon", "valuation": 14500000},
                                    {"deal_id": "DL-HERON", "codename": "Project Heron", "valuation": 38000000}]}
    masked = post(gate, "ian@bank.example", "ListDeals", output)["override"]["output"]
    assert masked["deals"][0]["codename"] == "Project Falcon"
    assert masked["deals"][1] == {"deal_id": "DL-HERON", "codename": RESTRICTED, "valuation": RESTRICTED}


def test_a_crossing_is_requested_decided_by_the_control_room_and_expires(arcade, graph):
    reply = desk(arcade)("I need to be brought over the wall on the Lakeside Bakehouse deal for a client pitch.")
    [request] = graph.requests.values()
    assert (request["action"], request["resource_id"], request["routed_to"]) == ("cross_wall", "DL-FALCON", "cora@bank.example")
    assert "Project Falcon" not in reply.text

    with pytest.raises(SystemExit, match="control room"):
        approvals(arcade, Settings(user="sana@bank.example"), request["request_id"], "approve", None)
    decided = approvals(arcade, CORA, request["request_id"], "approve", "Pitch prep with Mia, two hours.", hours=2)
    expires = datetime.fromisoformat(decided["expires_at"].replace("Z", "+00:00"))
    assert timedelta(hours=1, minutes=59) < expires - datetime.now(UTC) <= timedelta(hours=2)
    [crossing] = graph.crossings
    assert (crossing["email"], crossing["deal_id"], crossing["approved_by"]) == ("ian@bank.example", "DL-FALCON", "cora@bank.example")

    assert "deal_desk" in coordinator_tools(arcade, IAN)
    reply = desk(arcade)(BRIEF)
    assert "Project Falcon" in reply.text

    heron = desk(arcade, deal_desk=ScriptedModel(steps(Call("Bank_GetDeal", {"deal_id": "DL-HERON"}))))
    heron("What is the latest on DL-HERON?")
    assert next(c for c in heron.transcript.calls if c.name == "Bank_GetDeal").refused

    crossing["expires_at"] = "2020-01-01T00:00:00Z"
    assert "deal_desk" not in coordinator_tools(arcade, IAN)
    assert "Project Falcon" not in desk(arcade)(BRIEF).text


def test_a_crossing_lasts_at_most_a_day(arcade, graph):
    desk(arcade)("I need to be brought over the wall on the Lakeside Bakehouse deal.")
    [request_id] = list(graph.requests)
    decided = approvals(arcade, CORA, request_id, "approve", None, hours=100)
    expires = datetime.fromisoformat(decided["expires_at"].replace("Z", "+00:00"))
    assert expires - datetime.now(UTC) <= timedelta(hours=24)
