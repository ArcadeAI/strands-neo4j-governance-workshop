"""The loans tools: search, read, walk the ownership graph, approve, deny.

Nothing here decides whether a caller *may* do what they ask. That is the control plane's
question (`gate/`), answered by Arcade's contextual access hooks before and after each call,
on a path these tools cannot see. The tools record who acted, from `context.user_id`, the
identity Arcade executed the call as, and nothing else.

The tool descriptions are written to be picked by a model without prompt coaching. The
arguments are typed (`loan_id`, `amount`) so a policy can read them: an approval for $95,000
is a call with `amount=95000`, not a sentence the policy has to parse.
"""

# No `from __future__ import annotations` in a tools module: arcade-core reads each parameter's
# annotation as a live type to find the context argument and build the tool's schema.

from enum import Enum
from typing import Annotated, Any

from arcade_core.errors import ToolExecutionError
from arcade_mcp_server import Context
from arcade_mcp_server.metadata import Behavior, Operation, ToolMetadata

from loan_desk.app import app
from loan_desk.graph import SECRETS, Conflict, NotFound, book_for

__all__ = ["approve_loan", "deny_loan", "fold_network", "get_borrower_network", "get_loan", "search_loans"]

_read = ToolMetadata(
    behavior=Behavior(operations=[Operation.READ], read_only=True, destructive=False, idempotent=True, open_world=False),
)
_write = ToolMetadata(
    behavior=Behavior(operations=[Operation.CREATE], read_only=False, destructive=False, idempotent=False, open_world=False),
)


class LoanStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


LoanId = Annotated[str, "The loan application's ID, in the form LN-0000, for example LN-2291."]


def actor_of(context: Context) -> str:
    """Who Arcade executed this call as. A call with nobody behind it does nothing."""
    actor = (context.user_id or "").strip().lower()
    if not actor:
        raise ToolExecutionError(
            "Arcade did not say who is calling, so nothing was read or written.",
            developer_message="context.user_id was empty.",
        )
    return actor


async def _loan(context: Context, loan_id: str) -> dict[str, Any]:
    try:
        return await book_for(context).get_loan(loan_id)
    except NotFound as exc:
        raise ToolExecutionError(f"There is no loan application {loan_id}.") from exc


def fold_network(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The NETWORK query's rows as one answer: owners, the companies they also own, and the group's exposure."""
    first = rows[0]
    owners: dict[str, dict[str, Any]] = {}
    related: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("owner") is None:
            continue
        owner = owners.setdefault(row["owner"], {"name": row["owner"], "pct": row["owner_pct"], "also_owns": {}})
        if row.get("company") is None or row.get("related_loan_id") is None:
            continue
        company = owner["also_owns"].setdefault(row["company"], {"name": row["company"], "pct": row["company_pct"], "loans": []})
        loan = {"loan_id": row["related_loan_id"], "amount": row["related_amount"], "status": row["related_status"]}
        if loan not in company["loans"]:
            company["loans"].append(loan)
        related[loan["loan_id"]] = {**loan, "borrower_name": row["company"]}
    approved = sum(loan["amount"] for loan in related.values() if loan["status"] == "approved")
    pending = sum(loan["amount"] for loan in related.values() if loan["status"] == "pending")
    return {
        "loan_id": first["loan_id"],
        "borrower_name": first["borrower_name"],
        "amount": first["amount"],
        "status": first["status"],
        "owners": [{**o, "also_owns": list(o["also_owns"].values())} for o in owners.values()],
        "related_loans": sorted(related.values(), key=lambda loan: loan["loan_id"]),
        "group_exposure": {"approved": approved, "pending_elsewhere": pending, "this_loan": first["amount"]},
    }


@app.tool(requires_secrets=SECRETS, metadata=_read)
async def search_loans(
    context: Context,
    status: Annotated[LoanStatus | None, "Return only applications in this state. 'pending' means no decision has been recorded yet."] = None,
    min_amount: Annotated[float | None, "Return only applications for at least this many US dollars."] = None,
    max_amount: Annotated[float | None, "Return only applications for at most this many US dollars."] = None,
) -> Annotated[dict[str, Any], "The number of matching applications and their list-view fields."]:
    """Find loan applications in the loan book, newest submission first: what is awaiting a decision, or what falls within a dollar range. All filters are optional and combine; with none supplied this returns every application on file. Each hit carries the list-view fields only: ID, borrower, amount, status, purpose and submission date. The full file is in get_loan's result for an ID from these hits."""
    actor_of(context)
    loans = await book_for(context).search_loans(status.value if status else None, min_amount, max_amount)
    return {"count": len(loans), "loans": loans}


@app.tool(requires_secrets=SECRETS, metadata=_read)
async def get_loan(context: Context, loan_id: LoanId) -> Annotated[dict[str, Any], "The complete loan application record."]:
    """Read one loan application's complete file by ID: borrower details including the contact email the outcome is sent to, the requested amount and purpose, credit score, annual revenue and years in business, the underwriter's notes, the guarantors, the borrower's bank account number and tax ID, and every approval or denial already recorded against it, oldest first."""
    actor_of(context)
    return await _loan(context, loan_id)


@app.tool(requires_secrets=SECRETS, metadata=_read)
async def get_borrower_network(context: Context, loan_id: LoanId) -> Annotated[dict[str, Any], "The borrower's owners, the other companies they own, and those companies' loans."]:
    """Walk the ownership graph from one loan application: who owns the borrowing company, which other companies those owners also own, every loan application those companies have on file, and the group's exposure (approved elsewhere, pending elsewhere, and this loan). Use it to see the whole relationship before deciding a loan."""
    actor_of(context)
    try:
        rows = await book_for(context).borrower_network(loan_id)
    except NotFound as exc:
        raise ToolExecutionError(f"There is no loan application {loan_id}.") from exc
    return fold_network(rows)


@app.tool(requires_secrets=SECRETS, metadata=_write)
async def approve_loan(
    context: Context,
    loan_id: LoanId,
    amount: Annotated[float, "The amount to approve, in US dollars. It need not equal the amount requested: an application may be approved for less."],
) -> Annotated[dict[str, Any], "The application as it stands after the approval."]:
    """Approve a loan application for a given dollar amount, committing the decision to the loan book: the approval is appended to the application's decision history and its status becomes 'approved'. Returns the application as it stands after the approval."""
    actor = actor_of(context)
    if amount <= 0:
        raise ToolExecutionError(f"{amount!r} is not an amount that can be approved.")
    try:
        await book_for(context).record_decision(loan_id, "approved", amount, None, actor)
    except NotFound as exc:
        raise ToolExecutionError(f"There is no loan application {loan_id}.") from exc
    except Conflict as exc:
        raise ToolExecutionError(str(exc)) from exc
    return await _loan(context, loan_id)


@app.tool(requires_secrets=SECRETS, metadata=_write)
async def deny_loan(
    context: Context,
    loan_id: LoanId,
    reason: Annotated[str, "Why the application is being declined. Recorded verbatim in the decision history and read by auditors, so write it for a human."],
) -> Annotated[dict[str, Any], "The application as it stands after the denial."]:
    """Decline a loan application with a stated reason, committing the decision to the loan book: the denial is appended to the application's decision history and its status becomes 'denied'. Returns the application as it stands after the denial."""
    actor = actor_of(context)
    if not reason.strip():
        raise ToolExecutionError("A denial needs a reason.")
    try:
        await book_for(context).record_decision(loan_id, "denied", None, reason.strip(), actor)
    except NotFound as exc:
        raise ToolExecutionError(f"There is no loan application {loan_id}.") from exc
    except Conflict as exc:
        raise ToolExecutionError(str(exc)) from exc
    return await _loan(context, loan_id)
