"""The Bank tools on their own, against the in-memory graph: what they return, and how approvals are routed."""

import asyncio

import pytest
from arcade_core.errors import ToolExecutionError
from arcade_core.schema import ToolContext

from bank_tools import aml, approvals, banker, payments
from bank_tools.aml import fold_trace
from bank_tools.approvals import Action, Decision
from bank_tools.graph import use_book


@pytest.fixture(autouse=True)
def book(graph):
    use_book(lambda _context: graph.book())
    yield
    use_book(None)


def run(func, user="pat@bank.example", **inputs):
    return asyncio.run(func(ToolContext(user_id=user), **inputs))


def test_exceptions_are_listed_oldest_first():
    found = run(payments.list_payment_exceptions)
    assert [p["payment_id"] for p in found["payments"]] == ["PMT-5002", "PMT-5003", "PMT-5001"]


def test_screening_matches_names_and_aliases_but_not_owners():
    assert run(payments.screen_party, name="OML Shipping")["list_matches"][0]["entry"] == "SYN-SDN-0042"
    assert run(payments.screen_party, name="victor hale")["pep_matches"][0]["detail"].startswith("Former deputy mayor")
    assert run(payments.screen_party, name="Brightwater Trading LLC")["clear"] is True


def test_a_payment_is_decided_once(graph):
    run(payments.release_payment, payment_id="PMT-5003")
    assert graph.payments["PMT-5003"]["status"] == "released"
    with pytest.raises(ToolExecutionError, match="already released"):
        run(payments.hold_payment, payment_id="PMT-5003", reason="second thoughts")


def test_folding_a_trace_finds_the_ring():
    trace = fold_trace("ACC-HALE", asyncio.run(_paths()))
    assert trace["cycles"] == [["ACC-HALE", "ACC-REED", "ACC-MENDEZ", "ACC-PARK", "ACC-HALE"]]
    assert trace["total_out_first_hop"] == 24000
    assert {t["id"]: t["depth"] for t in trace["transfers"]}["T-0105"] == 2
    assert "ACC-HARBORVIEW" in trace["accounts_reached"]


async def _paths():
    from support.memory_graph import MemoryGraph

    return await MemoryGraph().book().trace_funds("ACC-HALE", 4)


def test_trace_funds_clamps_and_validates():
    assert run(aml.trace_funds, user="ava@bank.example", account_id="ACC-HALE", hops=99)["hops"] == 5
    with pytest.raises(ToolExecutionError):
        run(aml.trace_funds, user="ava@bank.example", account_id="ACC-NOPE", hops=2)


def test_ownership_carries_effective_percentages():
    found = run(aml.trace_ownership, user="ava@bank.example", party_id="P-HALE")
    by_name = {r["name"]: r for r in found["owns"]}
    assert by_name["Harborview Holdings Inc"]["effective_pct"] == 60.0
    assert by_name["Lumen Supply Co"]["chain"] == ["Victor Hale", "Greyline Ventures LLC", "Lumen Supply Co"]
    assert found["director_of"] == [{"company_id": "C-HARBORVIEW", "name": "Harborview Holdings Inc", "list_entry": None}]
    owners = run(aml.trace_ownership, user="ava@bank.example", party_id="C-ORLOV")
    assert owners["list_entry"] == "SYN-SDN-0042" and owners["directors"][0]["name"] == "Daniel Voss"


def test_a_sar_needs_a_real_narrative(graph):
    with pytest.raises(ToolExecutionError, match="too short"):
        run(aml.file_sar, user="ava@bank.example", case_id="CASE-7001", narrative="Suspicious.")
    assert graph.cases["CASE-7001"]["status"] == "open"


def test_a_profile_lists_the_companys_deals():
    profile = run(banker.get_company_profile, user="mia@bank.example", company_id="C-LAKESIDE")
    assert profile["coverage"] == ["Ian Moss"]
    assert profile["deals"] == [{"deal_id": "DL-FALCON", "codename": "Project Falcon", "role": "target", "counterparty": "Northwind Bakery LLC",
                                 "stage": "Exclusivity", "valuation": 14500000, "terms": profile["deals"][0]["terms"]}]


def test_a_release_goes_to_the_first_sanctions_officer_on_the_rota():
    request = run(approvals.request_approval, action=Action.RELEASE_PAYMENT, resource_id="PMT-5001", justification="Held at release.")
    assert request["routed_to"] == "sana@bank.example" and request["status"] == "pending"
    again = run(approvals.request_approval, action=Action.RELEASE_PAYMENT, resource_id="PMT-5001", justification="Again.")
    assert again["request_id"] == request["request_id"] and "already open" in again["message"]


def test_a_case_action_skips_the_owner_and_anyone_linked_to_the_subject():
    request = run(approvals.request_approval, user="ava@bank.example", action=Action.FREEZE_ACCOUNT, resource_id="ACC-HALE",
                  justification="Ring.", case_id="CASE-7001")
    assert request["routed_to"] == "dana@bank.example"
    assert [p["email"] for p in request["passed_over"]] == ["marco@bank.example"]
    with pytest.raises(ToolExecutionError, match="case_id"):
        run(approvals.request_approval, user="ava@bank.example", action=Action.FREEZE_ACCOUNT, resource_id="ACC-HALE", justification="x")


def test_a_sar_request_takes_its_case_from_the_resource():
    request = run(approvals.request_approval, user="ava@bank.example", action=Action.FILE_SAR, resource_id="CASE-7001", justification="x")
    assert request["case_id"] == "CASE-7001" and request["routed_to"] == "dana@bank.example"


def test_an_approved_crossing_writes_an_expiring_edge_and_a_denied_one_does_not(graph):
    first = run(approvals.request_approval, user="ian@bank.example", action=Action.CROSS_WALL, resource_id="DL-FALCON", justification="Pitch.")
    assert first["routed_to"] == "cora@bank.example"
    run(approvals.decide, user="cora@bank.example", request_id=first["request_id"], decision=Decision.DENIED, note="Not needed.")
    assert graph.crossings == []
    second = run(approvals.request_approval, user="ian@bank.example", action=Action.CROSS_WALL, resource_id="DL-FALCON", justification="Pitch.")
    decided = run(approvals.decide, user="cora@bank.example", request_id=second["request_id"], decision=Decision.APPROVED, hours=3)
    [edge] = graph.crossings
    assert edge["expires_at"] == decided["expires_at"] and edge["request_id"] == second["request_id"]
