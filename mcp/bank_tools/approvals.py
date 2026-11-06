"""The approvals tools: route a held action to the one person who may decide it, and record their answer.

`request_approval` is what an agent reaches for after the control plane refuses a call. The
refusal's own text is what sends it here; no agent's instructions mention approvals, because
a control the model is *asked* to respect is not a control.

Three things these tools do not do, each on purpose:

**They do not let anyone choose the approver.** Routing is deterministic: the first employee on
the rota with the role the action needs, never the requester and, for a case, never the case
owner or anyone with a path to the subject in the graph. A model that could name its own
approver could name a friendly one.

**They do not decide whether the caller may decide.** `decide` records an answer. Whether this
caller may give it (the right role, not the requester, no conflict with the subject) is a
pre-execution check on `Bank.Decide` in the control plane, made before this code runs.

**They do not hand out authority.** A request id is a pointer, not a capability. An approved
release, freeze or SAR only takes effect when the requester retries the original call and the
control plane finds the approved request for exactly that action and resource, once. The one
approval that does write is a wall-crossing: it becomes a `WALL_CROSSED` edge with an expiry,
which the control plane reads on every call until it lapses.
"""

# No `from __future__ import annotations` here: see common.py.

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Annotated, Any

from arcade_core.errors import ToolExecutionError
from arcade_mcp_server import Context

from bank_tools.app import app
from bank_tools.common import READ, WRITE, actor_of, graph_call
from bank_tools.graph import SECRETS, book_for, new_id, now

__all__ = ["CONFLICT_HOPS", "ROUTES", "decide", "list_approvals", "request_approval"]

ROUTES: dict[str, tuple[str, ...]] = {
    "release_payment": ("sanctions_officer",),
    "freeze_account": ("bsa_officer",),
    "file_sar": ("bsa_officer",),
    "cross_wall": ("compliance_officer",),
}
CASE_ACTIONS = {"freeze_account", "file_sar"}
CONFLICT_HOPS = 3
DEFAULT_CROSSING_HOURS = 4
MAX_CROSSING_HOURS = 24


class Action(str, Enum):
    RELEASE_PAYMENT = "release_payment"
    FREEZE_ACCOUNT = "freeze_account"
    FILE_SAR = "file_sar"
    CROSS_WALL = "cross_wall"


class Decision(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"


class RequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


def _public(request: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in request.items() if v is not None and k != "consumed_at"} | {"used": request.get("consumed_at") is not None}


@app.tool(requires_secrets=SECRETS, metadata=WRITE)
async def request_approval(
    context: Context,
    action: Annotated[Action, "The action the approval would cover."],
    resource_id: Annotated[str, "What the action acts on: a payment ID for release_payment, an account ID for freeze_account, a case ID for file_sar, a deal ID for cross_wall."],
    justification: Annotated[str, "The case for the action. The approver reads it verbatim."],
    case_id: Annotated[str | None, "The AML case the action belongs to. Required for freeze_account; for file_sar it is the resource_id."] = None,
) -> Annotated[dict[str, Any], "The request ID, its status, and the person it was routed to."]:
    """Record a request for one person's approval of an action. The request is routed to the first person on the rota with the role the action needs (a sanctions officer for a payment release, a BSA officer for a freeze or a SAR, the control room for a wall-crossing), never to the requester, and for a case never to its owner or anyone linked to its subject. Asking again for the same action and resource returns the request already open. Returns the request ID and who it went to."""
    requester = actor_of(context)
    action_name = action.value
    book = book_for(context)
    if await book.employee(requester) is None:
        raise ToolExecutionError(f"{requester} is not a Bowser Capital employee, so there is nobody to ask on behalf of.")

    subject = None
    if action_name in CASE_ACTIONS:
        case_id = case_id or (resource_id if action_name == "file_sar" else None)
        if not case_id:
            raise ToolExecutionError(f"A {action_name} request needs the case_id it belongs to.")
        subject = await book.case(case_id)
        if subject is None:
            raise ToolExecutionError(f"There is no case {case_id}.")

    existing = await book.open_request(action_name, resource_id, requester)
    if existing is not None:
        return {**_public(existing), "message": f"An approval request for this is already open with {existing['routed_to']}."}

    passed_over = []
    approver = None
    for candidate in await book.approvers(list(ROUTES[action_name])):
        if candidate["email"] == requester:
            continue
        if subject is not None and candidate["email"] == subject["owner"]:
            passed_over.append({"email": candidate["email"], "why": "owns the case"})
            continue
        if subject is not None:
            link = await book.linked(candidate["email"], subject["subject_id"], CONFLICT_HOPS)
            if link is not None:
                passed_over.append({"email": candidate["email"], "why": f"linked to the subject: {' - '.join(link['chain'])}"})
                continue
        approver = candidate
        break
    if approver is None:
        raise ToolExecutionError(f"Nobody without a conflict holds the role a {action_name} needs; the request was not recorded.")

    created = await graph_call(
        book.create_request(
            {
                "request_id": new_id("APR"),
                "action": action_name,
                "resource_id": resource_id,
                "case_id": case_id if action_name in CASE_ACTIONS else None,
                "justification": justification,
                "requested_by": requester,
                "routed_to": approver["email"],
                "created_at": now(),
            }
        ),
        "employee",
    )
    retry = "Once they approve it, retry the original call with the same arguments." if action_name != "cross_wall" else (
        "Once they approve it, the deal is open to you until the crossing expires."
    )
    return {
        **_public(created),
        "approver": {"name": approver["name"], "email": approver["email"], "role": approver["role"]},
        "passed_over": passed_over,
        "message": f"Approval request {created['request_id']} is with {approver['name']} ({approver['email']}). {retry}",
    }


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def list_approvals(
    context: Context,
    status: Annotated[RequestStatus | None, "Return only requests in this state."] = None,
) -> Annotated[dict[str, Any], "The approval requests the caller made or was asked to decide."]:
    """List the approval requests the caller made or was routed to decide, newest first, with each request's action, resource, justification, status, requester and approver."""
    user = actor_of(context)
    requests = await book_for(context).list_requests(user, status.value if status else None)
    return {"count": len(requests), "requests": [_public(r) for r in requests]}


@app.tool(requires_secrets=SECRETS, metadata=WRITE)
async def decide(
    context: Context,
    request_id: Annotated[str, "The approval request's ID, in the form APR-XXXXXXXX."],
    decision: Annotated[Decision, "The answer: approved or denied."],
    note: Annotated[str | None, "Why, in a sentence the requester will read."] = None,
    hours: Annotated[int | None, "For a wall-crossing only: how many hours the crossing lasts, 1 to 24. Defaults to 4."] = None,
) -> Annotated[dict[str, Any], "The approval request as it stands after the decision."]:
    """Record an answer to an approval request routed to you: approved or denied, with an optional note. An approved release, freeze or SAR lets the requester retry that one action once. An approved wall-crossing brings the requester over the wall for that deal until it expires."""
    actor = actor_of(context)
    book = book_for(context)
    request = await graph_call(book.get_request(request_id), "approval request")
    expires_at = None
    if request["action"] == "cross_wall" and decision is Decision.APPROVED:
        span = max(1, min(hours or DEFAULT_CROSSING_HOURS, MAX_CROSSING_HOURS))
        expires_at = (datetime.now(UTC).replace(microsecond=0) + timedelta(hours=span)).isoformat().replace("+00:00", "Z")
    decided = await graph_call(book.decide_request(request_id, decision.value, note, actor, expires_at), "approval request")
    if expires_at:
        await graph_call(book.cross_wall(request["requested_by"], request["resource_id"], expires_at, actor, request_id), "deal")
    return _public(decided)
