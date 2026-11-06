"""Where the loan desk's data lives: a Neo4j graph, reached with the server's own secrets.

The tools never see a connection string or a password. `arcade deploy` uploads NEO4J_URI,
NEO4J_USERNAME and NEO4J_PASSWORD from `mcp/.env` as Arcade secrets, and each call reads
them from its context. The model and the agent's laptop never hold them.

Every query is parameterized. A value a caller supplied goes in as a parameter, never into
the query text: the tools are typed so the policy can read their arguments, and the queries
are fixed so the model cannot write one.

`LoanBook` is the whole data interface the tools use. `Neo4jLoanBook` is the real one; the
tests swap in an in-memory graph through `use_book`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

NEO4J_URI = "NEO4J_URI"
NEO4J_USERNAME = "NEO4J_USERNAME"
NEO4J_PASSWORD = "NEO4J_PASSWORD"
SECRETS = [NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD]


class NotFound(LookupError):
    """No node with that id."""


class Conflict(ValueError):
    """The node is not in a state the write allows, such as a loan that is already decided."""


class LoanBook(Protocol):
    async def search_loans(self, status: str | None, min_amount: float | None, max_amount: float | None) -> list[dict[str, Any]]: ...
    async def get_loan(self, loan_id: str) -> dict[str, Any]: ...
    async def borrower_network(self, loan_id: str) -> list[dict[str, Any]]: ...
    async def record_decision(self, loan_id: str, decision: str, amount: float | None, reason: str | None, actor: str) -> None: ...
    async def approvers_for(self, amount: float, requester: str) -> list[dict[str, Any]]: ...
    async def officer(self, email: str) -> dict[str, Any] | None: ...
    async def open_request(self, action: str, resource_id: str, amount: float, requester: str) -> dict[str, Any] | None: ...
    async def create_request(self, request: dict[str, Any]) -> dict[str, Any]: ...
    async def get_request(self, request_id: str) -> dict[str, Any]: ...
    async def list_requests(self, user: str, status: str | None) -> list[dict[str, Any]]: ...
    async def decide_request(self, request_id: str, decision: str, note: str | None, actor: str) -> dict[str, Any]: ...


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


SEARCH = """
MATCH (c:Company)-[:APPLIED_FOR]->(l:Loan)
WHERE ($status IS NULL OR l.status = $status)
  AND ($min_amount IS NULL OR l.amount >= $min_amount)
  AND ($max_amount IS NULL OR l.amount <= $max_amount)
RETURN l.id AS loan_id, c.name AS borrower_name, l.amount AS amount, l.status AS status,
       l.purpose AS purpose, l.submitted_at AS submitted_at
ORDER BY l.submitted_at DESC
"""

GET = """
MATCH (c:Company)-[:APPLIED_FOR]->(l:Loan {id: $loan_id})
OPTIONAL MATCH (g:Person)-[:GUARANTEES]->(l)
WITH c, l, [name IN collect(DISTINCT g.name) WHERE name IS NOT NULL] AS guarantors
OPTIONAL MATCH (d:Decision)-[:ON]->(l)
WITH c, l, guarantors, d ORDER BY d.decided_at
WITH c, l, guarantors, [x IN collect(d) | {decision: x.kind, amount: x.amount, reason: x.reason,
     decided_at: x.decided_at, decided_by: x.decided_by}] AS decisions
RETURN l.id AS loan_id, c.name AS borrower_name, c.contact_email AS contact_email,
       l.amount AS amount, l.purpose AS purpose, l.status AS status, l.submitted_at AS submitted_at,
       l.credit_score AS credit_score, c.annual_revenue AS annual_revenue,
       c.years_in_business AS years_in_business, c.bank_account_number AS bank_account_number,
       c.tax_id AS tax_id, l.underwriter_notes AS underwriter_notes, guarantors, decisions
"""

# One row per (owner, related company, related loan). `loans.fold_network` folds the rows into
# the answer the tool returns, so the query stays a plain graph walk.
NETWORK = """
MATCH (c:Company)-[:APPLIED_FOR]->(l:Loan {id: $loan_id})
OPTIONAL MATCH (p:Person)-[o:OWNS]->(c)
OPTIONAL MATCH (p)-[o2:OWNS]->(other:Company)-[:APPLIED_FOR]->(ol:Loan)
WHERE ol <> l
RETURN c.name AS borrower_name, l.id AS loan_id, l.amount AS amount, l.status AS status,
       p.name AS owner, o.pct AS owner_pct, other.name AS company, o2.pct AS company_pct,
       ol.id AS related_loan_id, ol.amount AS related_amount, ol.status AS related_status
ORDER BY owner, company, related_loan_id
"""

DECIDE_LOAN = """
MATCH (l:Loan {id: $loan_id})
WHERE l.status = 'pending'
SET l.status = $decision
CREATE (d:Decision {id: $decision_id, kind: $decision, amount: $amount, reason: $reason,
                    decided_at: $at, decided_by: $actor})-[:ON]->(l)
WITH d
OPTIONAL MATCH (o:Officer {email: $actor})
FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END | MERGE (o)-[:MADE]->(d))
RETURN d.id AS id
"""

LOAN_STATUS = "MATCH (l:Loan {id: $loan_id}) RETURN l.status AS status"

APPROVERS = """
MATCH (o:Officer)
WHERE o.email <> $requester AND o.clearance >= $amount AND o.clearance > 0
RETURN o.email AS email, o.name AS name, o.role AS role, o.clearance AS clearance
ORDER BY o.clearance ASC, o.email ASC
"""

OFFICER = "MATCH (o:Officer {email: $email}) RETURN o.email AS email, o.name AS name, o.role AS role, o.clearance AS clearance"

REQUEST_FIELDS = """
r.id AS request_id, r.action AS action, r.resource_id AS resource_id, r.amount AS amount,
r.justification AS justification, r.status AS status, r.requested_by AS requested_by,
r.routed_to AS routed_to, r.created_at AS created_at, r.decided_by AS decided_by,
r.decided_at AS decided_at, r.note AS note, r.consumed_at AS consumed_at
"""

OPEN_REQUEST = f"""
MATCH (r:ApprovalRequest {{action: $action, resource_id: $resource_id, requested_by: $requester, status: 'pending'}})
WHERE r.amount = $amount
RETURN {REQUEST_FIELDS}
LIMIT 1
"""

CREATE_REQUEST = f"""
MATCH (req:Officer {{email: $requested_by}})
OPTIONAL MATCH (l:Loan {{id: $resource_id}})
OPTIONAL MATCH (ap:Officer {{email: $routed_to}})
CREATE (r:ApprovalRequest {{id: $request_id, action: $action, resource_id: $resource_id, amount: $amount,
                            justification: $justification, status: 'pending', requested_by: $requested_by,
                            routed_to: $routed_to, created_at: $created_at}})
CREATE (req)-[:REQUESTED]->(r)
FOREACH (_ IN CASE WHEN l IS NULL THEN [] ELSE [1] END | CREATE (r)-[:FOR]->(l))
FOREACH (_ IN CASE WHEN ap IS NULL THEN [] ELSE [1] END | CREATE (r)-[:ROUTED_TO]->(ap))
RETURN {REQUEST_FIELDS}
"""

GET_REQUEST = f"MATCH (r:ApprovalRequest {{id: $request_id}}) RETURN {REQUEST_FIELDS}"

LIST_REQUESTS = f"""
MATCH (r:ApprovalRequest)
WHERE (r.requested_by = $user OR r.routed_to = $user) AND ($status IS NULL OR r.status = $status)
RETURN {REQUEST_FIELDS}
ORDER BY r.created_at DESC
"""

DECIDE_REQUEST = f"""
MATCH (r:ApprovalRequest {{id: $request_id}})
WHERE r.status = 'pending'
SET r.status = $decision, r.decided_by = $actor, r.decided_at = $at, r.note = $note
WITH r
OPTIONAL MATCH (o:Officer {{email: $actor}})
FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END | MERGE (o)-[:DECIDED]->(r))
RETURN {REQUEST_FIELDS}
"""


class Neo4jLoanBook:
    """`LoanBook` over a Neo4j async driver."""

    def __init__(self, driver: Any, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    async def _rows(self, query: str, params: dict[str, Any], *, write: bool = False) -> list[dict[str, Any]]:
        from neo4j import RoutingControl

        records, _, _ = await self._driver.execute_query(
            query,
            params,
            database_=self._database,
            routing_=RoutingControl.WRITE if write else RoutingControl.READ,
        )
        return [dict(r) for r in records]

    async def search_loans(self, status, min_amount, max_amount):
        return await self._rows(SEARCH, {"status": status, "min_amount": min_amount, "max_amount": max_amount})

    async def get_loan(self, loan_id):
        rows = await self._rows(GET, {"loan_id": loan_id})
        if not rows:
            raise NotFound(loan_id)
        return rows[0]

    async def borrower_network(self, loan_id):
        rows = await self._rows(NETWORK, {"loan_id": loan_id})
        if not rows:
            raise NotFound(loan_id)
        return rows

    async def record_decision(self, loan_id, decision, amount, reason, actor):
        params = {
            "loan_id": loan_id, "decision": decision, "amount": amount, "reason": reason,
            "actor": actor, "at": now(), "decision_id": new_id("D"),
        }
        if await self._rows(DECIDE_LOAN, params, write=True):
            return
        status = await self._rows(LOAN_STATUS, {"loan_id": loan_id})
        if not status:
            raise NotFound(loan_id)
        raise Conflict(f"{loan_id} is already {status[0]['status']}.")

    async def approvers_for(self, amount, requester):
        return await self._rows(APPROVERS, {"amount": amount, "requester": requester})

    async def officer(self, email):
        rows = await self._rows(OFFICER, {"email": email})
        return rows[0] if rows else None

    async def open_request(self, action, resource_id, amount, requester):
        rows = await self._rows(OPEN_REQUEST, {"action": action, "resource_id": resource_id, "amount": amount, "requester": requester})
        return rows[0] if rows else None

    async def create_request(self, request):
        rows = await self._rows(CREATE_REQUEST, request, write=True)
        if not rows:
            raise NotFound(request["requested_by"])
        return rows[0]

    async def get_request(self, request_id):
        rows = await self._rows(GET_REQUEST, {"request_id": request_id})
        if not rows:
            raise NotFound(request_id)
        return rows[0]

    async def list_requests(self, user, status):
        return await self._rows(LIST_REQUESTS, {"user": user, "status": status})

    async def decide_request(self, request_id, decision, note, actor):
        rows = await self._rows(
            DECIDE_REQUEST,
            {"request_id": request_id, "decision": decision, "note": note, "actor": actor, "at": now()},
            write=True,
        )
        if rows:
            return rows[0]
        current = await self.get_request(request_id)
        raise Conflict(f"{request_id} is already {current['status']}.")


_drivers: dict[tuple[str, str], Any] = {}
_override: Callable[[Any], LoanBook] | None = None


def use_book(factory: Callable[[Any], LoanBook] | None) -> None:
    """Make every tool use `factory(context)` instead of Neo4j; `None` puts Neo4j back."""
    global _override
    _override = factory


def book_for(context: Any) -> LoanBook:
    """The loan book this call reads and writes, from the call's own secrets."""
    if _override is not None:
        return _override(context)
    from neo4j import AsyncGraphDatabase

    uri = context.get_secret(NEO4J_URI)
    user = context.get_secret(NEO4J_USERNAME)
    password = context.get_secret(NEO4J_PASSWORD)
    key = (uri, user)
    driver = _drivers.get(key)
    if driver is None:
        driver = _drivers[key] = AsyncGraphDatabase.driver(uri, auth=(user, password))
    return Neo4jLoanBook(driver, os.environ.get("NEO4J_DATABASE", "").strip() or "neo4j")
