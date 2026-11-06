"""The Loan Desk MCP server's tools, run as Arcade runs them, against the in-memory graph."""

import asyncio

import pytest
from arcade_core.errors import ToolExecutionError
from arcade_core.schema import ToolContext, ToolSecretItem

from loan_desk import approvals, loans
from loan_desk.graph import use_book
from loan_desk.loans import fold_network
from support.fake_arcade import loan_desk_definitions


@pytest.fixture
def book(graph):
    use_book(lambda _context: graph.book())
    yield graph
    use_book(None)


def ctx(user="alice@bank.example"):
    return ToolContext(user_id=user, secrets=[ToolSecretItem(key="NEO4J_URI", value="memory")])


def run(coro):
    return asyncio.run(coro)


def test_arcade_derives_eight_tools_with_typed_parameters():
    definitions = loan_desk_definitions()
    assert sorted(definitions) == sorted(
        ["SearchLoans", "GetLoan", "GetBorrowerNetwork", "ApproveLoan", "DenyLoan", "RequestApproval", "ListApprovals", "Decide"]
    )
    approve, _ = definitions["ApproveLoan"]
    params = {p["name"]: p for p in approve.parameters}
    assert params["amount"]["value_schema"]["val_type"] == "number"
    assert params["loan_id"]["required"]
    status = {p["name"]: p for p in definitions["SearchLoans"][0].parameters}["status"]
    assert status["value_schema"]["enum"] == ["pending", "approved", "denied"]


def test_search_filters_combine(book):
    found = run(loans.search_loans(ctx(), status=loans.LoanStatus.PENDING, min_amount=100000))
    assert {loan["loan_id"] for loan in found["loans"]} == {"LN-2290", "LN-2295"}


def test_get_loan_returns_the_file(book):
    loan = run(loans.get_loan(ctx(), "LN-2288"))
    assert loan["borrower_name"] == "Cedar Point Dental Group"
    assert loan["decisions"][0]["decided_by"] == "alice@bank.example"


def test_missing_loan_is_a_tool_error(book):
    with pytest.raises(ToolExecutionError):
        run(loans.get_loan(ctx(), "LN-0000"))


def test_borrower_network_walks_the_owners(book):
    network = run(loans.get_borrower_network(ctx(), "LN-2297"))
    assert network["borrower_name"] == "Lakeside Bakehouse LLC"
    elena = next(o for o in network["owners"] if o["name"] == "Elena Brandt")
    assert {c["name"] for c in elena["also_owns"]} == {"Northwind Bakery LLC", "Two Rivers Brewing Co"}
    assert network["group_exposure"]["approved"] == 47500
    assert network["group_exposure"]["pending_elsewhere"] == 95000


def test_fold_network_with_no_owners():
    rows = [{"borrower_name": "Solo", "loan_id": "LN-1", "amount": 10, "status": "pending", "owner": None, "owner_pct": None,
             "company": None, "company_pct": None, "related_loan_id": None, "related_amount": None, "related_status": None}]
    folded = fold_network(rows)
    assert folded["owners"] == [] and folded["group_exposure"]["approved"] == 0


def test_a_decided_loan_cannot_be_decided_again(book):
    with pytest.raises(ToolExecutionError, match="already approved"):
        run(loans.approve_loan(ctx(), "LN-2288", 38000))


def test_a_denial_needs_a_reason(book):
    with pytest.raises(ToolExecutionError):
        run(loans.deny_loan(ctx(), "LN-2292", "   "))


def test_no_identity_no_call(book):
    with pytest.raises(ToolExecutionError):
        run(loans.search_loans(ctx(user="")))


@pytest.mark.parametrize(
    ("requester", "amount", "approver"),
    [("alice@bank.example", 88000, "charlie@bank.example"), ("alice@bank.example", 300000, "michael@bank.example"),
     ("charlie@bank.example", 200000, "michael@bank.example")],
)
def test_requests_route_to_the_lowest_clearance_that_covers_them(book, requester, amount, approver):
    request = run(approvals.request_approval(ctx(requester), "approve_loan", "LN-2290", amount, "why"))
    assert request["routed_to"] == approver
    assert requester not in [request["routed_to"], *request["also_eligible"]]


def test_asking_twice_returns_the_open_request(book):
    first = run(approvals.request_approval(ctx(), "approve_loan", "LN-2299", 88000, "why"))
    second = run(approvals.request_approval(ctx(), "approve_loan", "LN-2299", 88000, "why again"))
    assert first["request_id"] == second["request_id"]
    assert len(book.requests) == 1


def test_nobody_can_cover_an_amount_above_every_clearance(book):
    with pytest.raises(ToolExecutionError, match="No officer"):
        run(approvals.request_approval(ctx(), "approve_loan", "LN-2290", 10_000_000, "why"))


def test_decide_records_once(book):
    request = run(approvals.request_approval(ctx(), "approve_loan", "LN-2299", 88000, "why"))
    decided = run(approvals.decide(ctx("charlie@bank.example"), request["request_id"], approvals.Decision.APPROVED, "ok"))
    assert decided["status"] == "approved" and decided["used"] is False
    with pytest.raises(ToolExecutionError, match="already approved"):
        run(approvals.decide(ctx("charlie@bank.example"), request["request_id"], approvals.Decision.DENIED, None))
    listed = run(approvals.list_approvals(ctx("charlie@bank.example")))
    assert listed["count"] == 1
