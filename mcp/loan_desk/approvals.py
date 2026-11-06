"""The approvals tools: escalate a refused call to the one officer who can decide it.

`request_approval` is what the agent reaches for after the control plane refuses an approval.
The refusal's own text is what sends it here; the agent's instructions say nothing about
limits, because a control the model is *asked* to respect is not a control.

Three things these tools do not do, each on purpose:

**They do not let anyone choose the approver.** Routing is deterministic: the lowest clearance
that covers the amount, the requester excluded, read from the officers in the graph. A model
that could name its own approver could name a friendly one.

**They do not decide whether the caller may decide.** `decide` records an answer. Whether this
caller may give it (enough clearance, and not the person who asked) is a pre-execution check
on `LoanDesk.Decide` in the control plane, made before this code runs.

**They do not hand out authority.** A request id is a pointer, not a capability. The approval
only takes effect when the requester retries the original call and the control plane finds the
approved request for exactly that loan and amount, once.
"""

# No `from __future__ import annotations` here: see loans.py.

from enum import Enum
from typing import Annotated, Any

from arcade_core.errors import ToolExecutionError
from arcade_mcp_server import Context
from arcade_mcp_server.metadata import Behavior, Operation, ToolMetadata

from loan_desk.app import app
from loan_desk.graph import SECRETS, Conflict, NotFound, book_for, new_id, now
from loan_desk.loans import actor_of

__all__ = ["decide", "list_approvals", "request_approval"]

_write = ToolMetadata(
    behavior=Behavior(operations=[Operation.CREATE], read_only=False, destructive=False, idempotent=False, open_world=False),
)
_read = ToolMetadata(
    behavior=Behavior(operations=[Operation.READ], read_only=True, destructive=False, idempotent=True, open_world=False),
)


class Decision(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"


class RequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


def _public(request: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in request.items() if v is not None and k != "consumed_at"} | {"used": request.get("consumed_at") is not None}


@app.tool(requires_secrets=SECRETS, metadata=_write)
async def request_approval(
    context: Context,
    action: Annotated[str, "The action the approval would cover, for example approve_loan."],
    resource_id: Annotated[str, "What the action would act on, such as a loan application's ID."],
    amount: Annotated[float, "The amount the approval would cover, in US dollars."],
    justification: Annotated[str, "The case for the action. The approver reads it verbatim."],
) -> Annotated[dict[str, Any], "The request ID, its status, and the officer it was routed to."]:
    """Record a request for one officer's approval of an action on a resource. The request is routed to the officer with the lowest approval authority that covers the amount, never to the requester. Asking again for the same action, resource and amount returns the request already open instead of a second one. Returns the request ID and who it went to."""
    requester = actor_of(context)
    if amount <= 0:
        raise ToolExecutionError(f"{amount!r} is not an amount that can be routed for approval.")
    book = book_for(context)
    if await book.officer(requester) is None:
        raise ToolExecutionError(f"{requester} is not an officer on this loan desk, so there is nobody to escalate on behalf of.")

    existing = await book.open_request(action, resource_id, amount, requester)
    if existing is not None:
        return {**_public(existing), "message": f"An approval request for this is already open with {existing['routed_to']}."}

    candidates = await book.approvers_for(amount, requester)
    if not candidates:
        raise ToolExecutionError(
            f"No officer other than you holds approval authority for {amount:,.0f}; the request was not recorded."
        )
    approver, passed_over = candidates[0], candidates[1:]
    created = await book.create_request(
        {
            "request_id": new_id("APR"),
            "action": action,
            "resource_id": resource_id,
            "amount": amount,
            "justification": justification,
            "requested_by": requester,
            "routed_to": approver["email"],
            "created_at": now(),
        }
    )
    return {
        **_public(created),
        "approver": {"name": approver["name"], "email": approver["email"], "role": approver["role"]},
        "also_eligible": [c["email"] for c in passed_over],
        "message": f"Approval request {created['request_id']} is with {approver['name']} ({approver['email']}). "
        "Once they approve it, retry the original call with the same arguments.",
    }


@app.tool(requires_secrets=SECRETS, metadata=_read)
async def list_approvals(
    context: Context,
    status: Annotated[RequestStatus | None, "Return only requests in this state."] = None,
) -> Annotated[dict[str, Any], "The approval requests the caller made or was asked to decide."]:
    """List the approval requests the caller made or was routed to decide, newest first, with each request's action, resource, amount, justification, status, requester and approver."""
    user = actor_of(context)
    requests = await book_for(context).list_requests(user, status.value if status else None)
    return {"count": len(requests), "requests": [_public(r) for r in requests]}


@app.tool(requires_secrets=SECRETS, metadata=_write)
async def decide(
    context: Context,
    request_id: Annotated[str, "The approval request's ID, in the form APR-XXXXXXXX."],
    decision: Annotated[Decision, "The answer: approved or denied."],
    note: Annotated[str | None, "Why, in a sentence the requester will read."] = None,
) -> Annotated[dict[str, Any], "The approval request as it stands after the decision."]:
    """Record an officer's answer to an approval request routed to them: approved or denied, with an optional note. An approved request lets the requester retry the action it covers once, for exactly the resource and amount it names."""
    actor = actor_of(context)
    try:
        decided = await book_for(context).decide_request(request_id, decision.value, note, actor)
    except NotFound as exc:
        raise ToolExecutionError(f"There is no approval request {request_id}.") from exc
    except Conflict as exc:
        raise ToolExecutionError(str(exc)) from exc
    return _public(decided)
