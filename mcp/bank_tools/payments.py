"""The payments desk's tools: the exception queue, one payment, name screening, release and hold.

`screen_party` is the bank's list screen: an exact match of a name against the sanctions list
and the PEP flags. It is the check every payments team has, and it is blind to ownership: a
beneficiary owned by someone who runs a listed company matches nothing. That gap is what the
control plane's graph check covers, before `release_payment` runs (gate/policies/02-payments.json).

Nothing here decides whether a caller may release a payment. The tools record who acted, from
`context.user_id`, and nothing else.
"""

# No `from __future__ import annotations` here: see common.py.

from typing import Annotated, Any

from arcade_core.errors import ToolExecutionError
from arcade_mcp_server import Context

from bank_tools.app import app
from bank_tools.common import READ, WRITE, actor_of, graph_call
from bank_tools.graph import SECRETS, book_for

__all__ = ["get_payment", "hold_payment", "list_payment_exceptions", "release_payment", "screen_party"]

PaymentId = Annotated[str, "The payment's ID, in the form PMT-0000, for example PMT-5001."]


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def list_payment_exceptions(context: Context) -> Annotated[dict[str, Any], "The payments waiting for review, oldest first."]:
    """List the outbound payments the bank's monitoring stopped for human review, oldest first: ID, amount, originator, beneficiary and the alert that stopped it. Each payment's full record, including the reference text, is in get_payment's result."""
    actor_of(context)
    payments = await book_for(context).payment_exceptions()
    return {"count": len(payments), "payments": payments}


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def get_payment(context: Context, payment_id: PaymentId) -> Annotated[dict[str, Any], "The payment's full record."]:
    """Read one payment's full record: amount and currency, status, the alert that stopped it, the free-text reference the originator wrote, and the originating and beneficiary accounts with their holders and banks."""
    actor_of(context)
    return await graph_call(book_for(context).get_payment(payment_id), "payment")


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def screen_party(
    context: Context,
    name: Annotated[str, "The person's or company's name exactly as it appears on the payment or account, for example Brightwater Trading LLC."],
) -> Annotated[dict[str, Any], "List and PEP matches for the name, and whether it is clear."]:
    """Screen one name against the sanctions list and the bank's politically exposed person (PEP) records: an exact, case-insensitive match on the listed name or a known alias. Returns every match, and clear=true when there is none. It screens the name only, not who owns or controls the party."""
    actor_of(context)
    if not name.strip():
        raise ToolExecutionError("Give a name to screen.")
    found = await book_for(context).screen_party(name)
    return {"name": name.strip(), **found, "clear": not (found["list_matches"] or found["pep_matches"])}


@app.tool(requires_secrets=SECRETS, metadata=WRITE)
async def release_payment(context: Context, payment_id: PaymentId) -> Annotated[dict[str, Any], "The payment as it stands after the release."]:
    """Release a payment that is waiting for review, so it is sent to the beneficiary's bank. The release is recorded with who made it. Returns the payment as it stands afterwards."""
    actor = actor_of(context)
    book = book_for(context)
    await graph_call(book.set_payment_status(payment_id, "released", actor, None), "payment")
    return await graph_call(book.get_payment(payment_id), "payment")


@app.tool(requires_secrets=SECRETS, metadata=WRITE)
async def hold_payment(
    context: Context,
    payment_id: PaymentId,
    reason: Annotated[str, "Why the payment is held. Recorded verbatim and read by the sanctions team, so write it for a human."],
) -> Annotated[dict[str, Any], "The payment as it stands after the hold."]:
    """Hold a payment that is waiting for review, so it is not sent, with the reason recorded. Returns the payment as it stands afterwards."""
    actor = actor_of(context)
    if not reason.strip():
        raise ToolExecutionError("A hold needs a reason.")
    book = book_for(context)
    await graph_call(book.set_payment_status(payment_id, "held", actor, reason.strip()), "payment")
    return await graph_call(book.get_payment(payment_id), "payment")
