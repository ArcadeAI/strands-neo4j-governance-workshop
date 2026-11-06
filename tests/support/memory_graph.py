"""The loan desk graph in memory, from the same `seed.json` Neo4j is loaded from.

One `MemoryGraph` is both sides of the real deployment: `.book()` is the `LoanBook` the Loan
Desk tools write through, and the graph itself is the `Directory` the control plane reads. An
approval Charlie records through the tools is the grant the gate finds on Alice's retry,
exactly as when both talk to one Neo4j database.

Each method mirrors one Cypher query in `mcp/loan_desk/graph.py` or `gate/loan_gate/directory.py`.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from loan_graph import load_seed


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class MemoryGraph:
    def __init__(self, seed: dict[str, Any] | None = None) -> None:
        seed = copy.deepcopy(seed or load_seed())
        self.officers = {o["email"]: o for o in seed["officers"]}
        self.people = {p["id"]: p for p in seed["people"]}
        self.companies = {c["id"]: c for c in seed["companies"]}
        self.ownership = seed["ownership"]
        self.loans = {loan["loan_id"]: loan for loan in seed["loans"]}
        self.requests: dict[str, dict[str, Any]] = {}
        self.healthy = True

    def book(self) -> MemoryBook:
        return MemoryBook(self)

    def company_of(self, loan: dict[str, Any]) -> dict[str, Any]:
        return self.companies[loan["company"]]

    def owners_of(self, company_id: str) -> list[tuple[str, float]]:
        return [(o["person"], o["pct"]) for o in self.ownership if o["company"] == company_id]

    def owned_by(self, person_id: str) -> list[tuple[str, float]]:
        return [(o["company"], o["pct"]) for o in self.ownership if o["person"] == person_id]

    def loans_of(self, company_id: str) -> list[dict[str, Any]]:
        return [loan for loan in self.loans.values() if loan["company"] == company_id]

    # Directory: what the gate reads.

    def officer(self, email: str) -> dict[str, Any] | None:
        officer = self.officers.get(email)
        return dict(officer) if officer else None

    def request(self, request_id: str) -> dict[str, Any] | None:
        request = self.requests.get(request_id)
        return dict(request) if request else None

    def find_grant(self, requester: str, action: str, resource_id: str, amount: float) -> dict[str, Any] | None:
        for r in sorted(self.requests.values(), key=lambda r: r.get("decided_at") or ""):
            if (
                r["requested_by"] == requester and r["action"] == action and r["resource_id"] == resource_id
                and r["status"] == "approved" and r["amount"] == amount and r.get("consumed_at") is None
                and r.get("decided_by") != requester
            ):
                return {"request_id": r["request_id"], "decided_by": r["decided_by"], "amount": r["amount"]}
        return None

    def consume_grant(self, request_id: str, at: str) -> bool:
        r = self.requests.get(request_id)
        if r is None or r["status"] != "approved" or r.get("consumed_at") is not None:
            return False
        r["consumed_at"] = at
        return True

    def group_exposure(self, loan_id: str) -> float:
        this = self.loans[loan_id]
        group = {this["company"]}
        for person, _ in self.owners_of(this["company"]):
            group |= {company for company, _ in self.owned_by(person)}
        return float(sum(
            loan["amount"] for loan in self.loans.values()
            if loan["company"] in group and loan["status"] == "approved" and loan["loan_id"] != loan_id
        ))

    def ping(self) -> bool:
        return self.healthy


class MemoryBook:
    """`LoanBook` over a `MemoryGraph`."""

    def __init__(self, graph: MemoryGraph) -> None:
        self.graph = graph

    async def search_loans(self, status, min_amount, max_amount):
        rows = [
            {"loan_id": loan["loan_id"], "borrower_name": self.graph.company_of(loan)["name"], "amount": loan["amount"],
             "status": loan["status"], "purpose": loan["purpose"], "submitted_at": loan["submitted_at"]}
            for loan in self.graph.loans.values()
            if (status is None or loan["status"] == status)
            and (min_amount is None or loan["amount"] >= min_amount)
            and (max_amount is None or loan["amount"] <= max_amount)
        ]
        return sorted(rows, key=lambda r: r["submitted_at"], reverse=True)

    async def get_loan(self, loan_id):
        loan = self.graph.loans.get(loan_id)
        if loan is None:
            from loan_desk.graph import NotFound as BookNotFound

            raise BookNotFound(loan_id)
        company = self.graph.company_of(loan)
        decisions = sorted(loan["decisions"], key=lambda d: d["decided_at"])
        return {
            "loan_id": loan_id, "borrower_name": company["name"], "contact_email": company["contact_email"],
            "amount": loan["amount"], "purpose": loan["purpose"], "status": loan["status"],
            "submitted_at": loan["submitted_at"], "credit_score": loan["credit_score"],
            "annual_revenue": company["annual_revenue"], "years_in_business": company["years_in_business"],
            "bank_account_number": company["bank_account_number"], "tax_id": company["tax_id"],
            "underwriter_notes": loan["underwriter_notes"],
            "guarantors": [self.graph.people[p]["name"] for p in loan["guarantors"]],
            "decisions": [
                {"decision": d["decision"], "amount": d["amount"], "reason": d["reason"],
                 "decided_at": d["decided_at"], "decided_by": d["decided_by"]}
                for d in decisions
            ],
        }

    async def borrower_network(self, loan_id):
        loan = self.graph.loans.get(loan_id)
        if loan is None:
            from loan_desk.graph import NotFound as BookNotFound

            raise BookNotFound(loan_id)
        company = self.graph.company_of(loan)
        base = {"borrower_name": company["name"], "loan_id": loan_id, "amount": loan["amount"], "status": loan["status"]}
        empty = {"company": None, "company_pct": None, "related_loan_id": None, "related_amount": None, "related_status": None}
        rows = []
        owners = self.graph.owners_of(loan["company"])
        if not owners:
            return [{**base, "owner": None, "owner_pct": None, **empty}]
        for person, pct in owners:
            owner = {**base, "owner": self.graph.people[person]["name"], "owner_pct": pct}
            related = [
                {"company": self.graph.companies[cid]["name"], "company_pct": cpct, "related_loan_id": other["loan_id"],
                 "related_amount": other["amount"], "related_status": other["status"]}
                for cid, cpct in self.graph.owned_by(person)
                for other in self.graph.loans_of(cid)
                if other["loan_id"] != loan_id
            ]
            rows += [{**owner, **r} for r in related] or [{**owner, **empty}]
        return sorted(rows, key=lambda r: (r["owner"] or "", r["company"] or "", r["related_loan_id"] or ""))

    async def record_decision(self, loan_id, decision, amount, reason, actor):
        from loan_desk.graph import Conflict
        from loan_desk.graph import NotFound as BookNotFound

        loan = self.graph.loans.get(loan_id)
        if loan is None:
            raise BookNotFound(loan_id)
        if loan["status"] != "pending":
            raise Conflict(f"{loan_id} is already {loan['status']}.")
        loan["status"] = decision
        loan["decisions"].append({"id": f"D-{len(loan['decisions']) + 1}", "decision": decision, "amount": amount,
                                  "reason": reason, "decided_at": _now(), "decided_by": actor})

    async def approvers_for(self, amount, requester):
        found = [dict(o) for o in self.graph.officers.values() if o["email"] != requester and o["clearance"] >= amount and o["clearance"] > 0]
        return sorted(found, key=lambda o: (o["clearance"], o["email"]))

    async def officer(self, email):
        return self.graph.officer(email)

    async def open_request(self, action, resource_id, amount, requester):
        for r in self.graph.requests.values():
            if (r["action"], r["resource_id"], r["requested_by"], r["status"]) == (action, resource_id, requester, "pending") and r["amount"] == amount:
                return dict(r)
        return None

    async def create_request(self, request):
        from loan_desk.graph import NotFound as BookNotFound

        if request["requested_by"] not in self.graph.officers:
            raise BookNotFound(request["requested_by"])
        stored = {**request, "status": "pending", "decided_by": None, "decided_at": None, "note": None, "consumed_at": None}
        self.graph.requests[request["request_id"]] = stored
        return dict(stored)

    async def get_request(self, request_id):
        from loan_desk.graph import NotFound as BookNotFound

        if request_id not in self.graph.requests:
            raise BookNotFound(request_id)
        return dict(self.graph.requests[request_id])

    async def list_requests(self, user, status):
        rows = [dict(r) for r in self.graph.requests.values()
                if user in (r["requested_by"], r["routed_to"]) and (status is None or r["status"] == status)]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    async def decide_request(self, request_id, decision, note, actor):
        from loan_desk.graph import Conflict

        current = await self.get_request(request_id)
        if current["status"] != "pending":
            raise Conflict(f"{request_id} is already {current['status']}.")
        self.graph.requests[request_id].update(status=decision, decided_by=actor, decided_at=_now(), note=note)
        return dict(self.graph.requests[request_id])
