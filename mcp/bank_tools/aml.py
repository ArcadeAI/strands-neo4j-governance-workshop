"""The AML case team's tools: read a case, follow the money, follow the ownership, freeze, file a SAR.

`trace_funds` and `trace_ownership` are the two questions a graph answers in one query that a
table answers in a loop: where did this money go, hop by hop, and did any of it come back; and
who is behind this company, through how many shells. The ring in CASE-7001 is a cycle in the
first and a two-level chain in the second.

`freeze_account` and `file_sar` record a decision. Whether this caller may make it alone is
the control plane's question: both need a second person (four eyes), checked before they run.
"""

# No `from __future__ import annotations` here: see common.py.

from typing import Annotated, Any

from arcade_core.errors import ToolExecutionError
from arcade_mcp_server import Context

from bank_tools.app import app
from bank_tools.common import READ, WRITE, actor_of, graph_call
from bank_tools.graph import SECRETS, book_for, clamp_hops

__all__ = ["file_sar", "fold_trace", "freeze_account", "get_case", "trace_funds", "trace_ownership"]

CaseId = Annotated[str, "The AML case's ID, in the form CASE-0000, for example CASE-7001."]
AccountId = Annotated[str, "The account's ID, in the form ACC-NAME, for example ACC-HALE."]


def fold_trace(account_id: str, paths: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Every PAID path out of an account as one answer: each transfer once, at its shallowest depth, and the cycles."""
    transfers: dict[str, dict[str, Any]] = {}
    cycles: list[list[str]] = []
    for path in paths:
        for depth, step in enumerate(path, start=1):
            known = transfers.get(step["id"])
            if known is None or depth < known["depth"]:
                transfers[step["id"]] = {**step, "depth": depth}
        if path and path[-1]["to"] == account_id:
            cycle = [path[0]["from"], *(step["to"] for step in path)]
            if cycle not in cycles:
                cycles.append(cycle)
    rows = sorted(transfers.values(), key=lambda t: (t["depth"], t["at"], t["id"]))
    reached = sorted({t["to"] for t in rows} - {account_id})
    return {
        "account_id": account_id,
        "transfers": rows,
        "accounts_reached": reached,
        "cycles": sorted(cycles, key=len),
        "total_out_first_hop": sum(t["amount"] for t in rows if t["depth"] == 1),
    }


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def get_case(context: Context, case_id: CaseId) -> Annotated[dict[str, Any], "The case, its subject and the subject's accounts."]:
    """Read one AML case: its status, the alert that opened it, the investigator who owns it, the subject (name, date of birth, SSN, PEP status) and every account the subject holds at the bank."""
    actor_of(context)
    return await graph_call(book_for(context).get_case(case_id), "case")


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def trace_funds(
    context: Context,
    account_id: AccountId,
    hops: Annotated[int, "How many transfers deep to follow the money, 1 to 5. Use 4 to find a ring."] = 4,
) -> Annotated[dict[str, Any], "Every transfer reachable from the account, and the cycles back to it."]:
    """Follow the money out of one account through the transfer graph, up to a number of hops: every transfer on the way (from, to, amount, time, and how many hops out it is), every account reached, and every cycle where money came back to the starting account. A cycle is how a mule ring launders funds back to its originator."""
    actor_of(context)
    if hops < 1:
        raise ToolExecutionError("hops is at least 1.")
    paths = await graph_call(book_for(context).trace_funds(account_id, hops), "account")
    return {**fold_trace(account_id, paths), "hops": clamp_hops(hops)}


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def trace_ownership(
    context: Context,
    party_id: Annotated[str, "The person's or company's ID, for example P-HALE or C-GREYLINE."],
) -> Annotated[dict[str, Any], "Who the party owns and is owned by, through every level, and its directorships and accounts."]:
    """Walk the ownership graph from one person or company, up to four levels each way: the companies it owns directly and through other companies (with each chain and its percentages), who owns it, the boards it sits on or the directors it has, and the accounts it holds. Listed entities carry their list entry."""
    actor_of(context)
    found = await graph_call(book_for(context).trace_ownership(party_id), "party")
    for key in ("owns", "owned_by"):
        for row in found[key]:
            effective = 1.0
            for pct in row.pop("pcts"):
                effective *= (pct or 0) / 100
            row["effective_pct"] = round(effective * 100, 1)
        found[key] = sorted(found[key], key=lambda r: (len(r["chain"]), r["name"]))
    return found


@app.tool(requires_secrets=SECRETS, metadata=WRITE)
async def freeze_account(
    context: Context,
    account_id: AccountId,
    case_id: CaseId,
    reason: Annotated[str, "Why the account is frozen. Recorded on the case and read by examiners."],
) -> Annotated[dict[str, Any], "The account's new status."]:
    """Freeze one account under an open AML case, so no money moves in or out until it is unfrozen. Recorded on the case with who froze it and why."""
    actor = actor_of(context)
    if not reason.strip():
        raise ToolExecutionError("A freeze needs a reason.")
    await graph_call(book_for(context).freeze_account(account_id, case_id, reason.strip(), actor), "account or case")
    return {"account_id": account_id, "case_id": case_id, "status": "frozen", "frozen_by": actor}


@app.tool(requires_secrets=SECRETS, metadata=WRITE)
async def file_sar(
    context: Context,
    case_id: CaseId,
    narrative: Annotated[str, "The SAR narrative: who, what, when, where and why the activity is suspicious, in plain language."],
) -> Annotated[dict[str, Any], "The filed SAR's ID and the case's new status."]:
    """File a Suspicious Activity Report (SAR) for an open AML case, recording the narrative given for submission to FinCEN. The case's status becomes sar_filed. A SAR and the fact that one was filed are confidential."""
    actor = actor_of(context)
    if len(narrative.strip()) < 40:
        raise ToolExecutionError("A SAR narrative must say who, what, when, where and why; this one is too short to file.")
    filed = await graph_call(book_for(context).file_sar(case_id, narrative.strip(), actor), "case")
    return {"case_id": case_id, "status": "sar_filed", **filed}
