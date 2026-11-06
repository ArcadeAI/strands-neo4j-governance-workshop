"""What the control plane reads from the graph: who an officer is, and what approvals exist.

The gate runs on your side, not Arcade's, and reads the same Neo4j database the Loan Desk
tools write to. That is how an approval Charlie records through `LoanDesk.Decide` becomes the
single-use grant that lets Alice's retry through.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Protocol


class Directory(Protocol):
    def officer(self, email: str) -> dict[str, Any] | None: ...
    def request(self, request_id: str) -> dict[str, Any] | None: ...
    def find_grant(self, requester: str, action: str, resource_id: str, amount: float) -> dict[str, Any] | None: ...
    def consume_grant(self, request_id: str, at: str) -> bool: ...
    def group_exposure(self, loan_id: str) -> float: ...
    def ping(self) -> bool: ...


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


OFFICER = "MATCH (o:Officer {email: $email}) RETURN o.email AS email, o.name AS name, o.role AS role, o.clearance AS clearance"

REQUEST = """
MATCH (r:ApprovalRequest {id: $request_id})
RETURN r.id AS request_id, r.action AS action, r.resource_id AS resource_id, r.amount AS amount,
       r.status AS status, r.requested_by AS requested_by, r.routed_to AS routed_to,
       r.decided_by AS decided_by, r.consumed_at AS consumed_at
"""

FIND_GRANT = """
MATCH (r:ApprovalRequest {requested_by: $requester, action: $action, resource_id: $resource_id, status: 'approved'})
WHERE r.amount = $amount AND r.consumed_at IS NULL AND r.decided_by <> $requester
RETURN r.id AS request_id, r.decided_by AS decided_by, r.amount AS amount
ORDER BY r.decided_at
LIMIT 1
"""

CONSUME_GRANT = """
MATCH (r:ApprovalRequest {id: $request_id})
WHERE r.status = 'approved' AND r.consumed_at IS NULL
SET r.consumed_at = $at
RETURN r.id AS request_id
"""

# Approved loans of every company that shares an owner with this loan's borrower, the
# borrower included, this loan excluded.
GROUP_EXPOSURE = """
MATCH (c:Company)-[:APPLIED_FOR]->(this:Loan {id: $loan_id})
OPTIONAL MATCH (c)<-[:OWNS]-(:Person)-[:OWNS]->(other:Company)
WITH this, c, collect(DISTINCT other) AS others
UNWIND [c] + others AS g
MATCH (g)-[:APPLIED_FOR]->(gl:Loan {status: 'approved'})
WHERE gl <> this
WITH DISTINCT gl
RETURN coalesce(sum(gl.amount), 0) AS approved
"""


class Neo4jDirectory:
    def __init__(self, driver: Any, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    @classmethod
    def from_env(cls) -> Neo4jDirectory:
        from neo4j import GraphDatabase

        uri = os.environ.get("NEO4J_URI", "").strip()
        if not uri:
            raise RuntimeError("NEO4J_URI is not set; the gate reads officers and approvals from the graph.")
        driver = GraphDatabase.driver(uri, auth=(os.environ.get("NEO4J_USERNAME", "neo4j"), os.environ.get("NEO4J_PASSWORD", "")))
        return cls(driver, os.environ.get("NEO4J_DATABASE", "").strip() or "neo4j")

    def _rows(self, query: str, params: dict[str, Any], *, write: bool = False) -> list[dict[str, Any]]:
        from neo4j import RoutingControl

        records, _, _ = self._driver.execute_query(
            query, params, database_=self._database, routing_=RoutingControl.WRITE if write else RoutingControl.READ
        )
        return [dict(r) for r in records]

    def officer(self, email):
        rows = self._rows(OFFICER, {"email": email})
        return rows[0] if rows else None

    def request(self, request_id):
        rows = self._rows(REQUEST, {"request_id": request_id})
        return rows[0] if rows else None

    def find_grant(self, requester, action, resource_id, amount):
        rows = self._rows(FIND_GRANT, {"requester": requester, "action": action, "resource_id": resource_id, "amount": amount})
        return rows[0] if rows else None

    def consume_grant(self, request_id, at):
        return bool(self._rows(CONSUME_GRANT, {"request_id": request_id, "at": at}, write=True))

    def group_exposure(self, loan_id):
        rows = self._rows(GROUP_EXPOSURE, {"loan_id": loan_id})
        return float(rows[0]["approved"]) if rows else 0.0

    def ping(self):
        try:
            self._driver.verify_connectivity()
        except Exception:  # noqa: BLE001 - any failure means unhealthy
            return False
        return True
