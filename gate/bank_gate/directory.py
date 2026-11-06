"""What the control plane asks the graph: who someone is, what approvals exist, and how things connect.

The gate runs on your side, not Arcade's, and reads the same Neo4j database the Bank tools write
to. That is how an approval Sana records through `Bank.Decide` becomes the single-use grant that
lets Pat's retry through, and how a wall-crossing Cora approves opens a deal to Ian until it
expires.

Most of what the policy needs is a path question: how many hops from this beneficiary to a
listed entity, from this email recipient to the subject of an open case, from this approver to
the subject they would rule on. Each is one `shortestPath` query here. The path length is a
policy constant, an int formatted into the query because Cypher takes no parameter there.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Protocol

CONTROL = "HOLDS|OWNS|DIRECTOR_OF"
LINKS = "HOLDS|OWNS|DIRECTOR_OF|MANAGES|IS"
MAX_HOPS = 6


class Directory(Protocol):
    def employee(self, email: str) -> dict[str, Any] | None: ...
    def request(self, request_id: str) -> dict[str, Any] | None: ...
    def find_grant(self, requester: str, action: str, resource_id: str) -> dict[str, Any] | None: ...
    def consume_grant(self, request_id: str, at: str) -> bool: ...
    def sanctions_proximity(self, payment_id: str, hops: int) -> dict[str, Any] | None: ...
    def inbound_near_threshold(self, payment_id: str, floor: float, threshold: float, window_days: int) -> dict[str, Any] | None: ...
    def case_subject_near(self, recipient: str, hops: int) -> dict[str, Any] | None: ...
    def case(self, case_id: str) -> dict[str, Any] | None: ...
    def linked(self, email: str, party_id: str, hops: int) -> dict[str, Any] | None: ...
    def deals_open_to(self, email: str, at: str) -> list[str]: ...
    def ping(self) -> bool: ...


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bounded(hops: int) -> int:
    return max(1, min(int(hops), MAX_HOPS))


EMPLOYEE = "MATCH (e:Employee {email: $email}) RETURN e.email AS email, e.name AS name, e.role AS role, e.desk AS desk"

REQUEST = """
MATCH (r:ApprovalRequest {id: $request_id})
RETURN r.id AS request_id, r.action AS action, r.resource_id AS resource_id, r.case_id AS case_id,
       r.status AS status, r.requested_by AS requested_by, r.routed_to AS routed_to,
       r.decided_by AS decided_by, r.consumed_at AS consumed_at
"""

FIND_GRANT = """
MATCH (r:ApprovalRequest {requested_by: $requester, action: $action, resource_id: $resource_id, status: 'approved'})
WHERE r.consumed_at IS NULL AND r.decided_by <> $requester
RETURN r.id AS request_id, r.decided_by AS decided_by
ORDER BY r.decided_at
LIMIT 1
"""

CONSUME_GRANT = """
MATCH (r:ApprovalRequest {id: $request_id})
WHERE r.status = 'approved' AND r.consumed_at IS NULL
SET r.consumed_at = $at
RETURN r.id AS request_id
"""

SANCTIONS_PROXIMITY = """
MATCH (:Payment {{id: $payment_id}})-[:TO]->(acct:Account)
MATCH (s:Sanctioned)
MATCH path = shortestPath((acct)-[:{control}*..{hops}]-(s))
RETURN length(path) AS hops, s.list_entry AS entry, s.name AS listed,
       [n IN nodes(path) | coalesce(n.name, n.id)] AS chain
ORDER BY hops, entry
LIMIT 1
"""

INBOUND_NEAR_THRESHOLD = """
MATCH (p:Payment {id: $payment_id})-[:TO]->(acct:Account)<-[:HOLDS]-(holder:Party)
OPTIONAL MATCH (src:Account)-[t:PAID]->(acct)
WHERE t.amount >= $floor AND t.amount < $threshold
  AND datetime(t.at) <= datetime(p.created_at)
  AND datetime(t.at) >= datetime(p.created_at) - duration({days: $window_days})
RETURN p.amount AS amount, holder.name AS beneficiary, count(t) AS count, count(DISTINCT src) AS senders,
       coalesce(sum(t.amount), 0) AS total
"""

CASE_SUBJECT_NEAR = """
MATCH (e:Employee) WHERE e.email = $recipient OR e.slack = $recipient
MATCH (c:Case)-[:SUBJECT]->(s:Party) WHERE c.status <> 'closed'
MATCH path = shortestPath((e)-[:{links}*..{hops}]-(s))
RETURN c.id AS case_id, s.name AS subject, length(path) AS hops, [n IN nodes(path) | coalesce(n.name, n.id)] AS chain
ORDER BY hops, case_id
LIMIT 1
"""

CASE = """
MATCH (c:Case {id: $case_id})-[:SUBJECT]->(s:Party)
RETURN c.id AS case_id, c.owner AS owner, c.status AS status, s.id AS subject_id, s.name AS subject
"""

LINKED = """
MATCH (e:Employee {{email: $email}}), (s:Party {{id: $party_id}})
MATCH path = shortestPath((e)-[:{links}*..{hops}]-(s))
RETURN length(path) AS hops, [n IN nodes(path) | coalesce(n.name, n.id)] AS chain
"""

DEALS_OPEN_TO = """
MATCH (e:Employee {email: $email})
OPTIONAL MATCH (e)-[:INSIDER_ON]->(inside:Deal)
WITH e, collect(inside.id) AS insider
OPTIONAL MATCH (e)-[w:WALL_CROSSED]->(crossed:Deal)
WHERE w.expires_at > $at
WITH insider, collect(crossed.id) AS crossings
RETURN insider + crossings AS deals
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
            raise RuntimeError("NEO4J_URI is not set; the gate reads employees, approvals and paths from the graph.")
        driver = GraphDatabase.driver(uri, auth=(os.environ.get("NEO4J_USERNAME", "neo4j"), os.environ.get("NEO4J_PASSWORD", "")))
        return cls(driver, os.environ.get("NEO4J_DATABASE", "").strip() or "neo4j")

    def _rows(self, query: str, params: dict[str, Any], *, write: bool = False) -> list[dict[str, Any]]:
        from neo4j import RoutingControl

        records, _, _ = self._driver.execute_query(
            query, params, database_=self._database, routing_=RoutingControl.WRITE if write else RoutingControl.READ
        )
        return [dict(r) for r in records]

    def _first(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        rows = self._rows(query, params)
        return rows[0] if rows else None

    def employee(self, email):
        return self._first(EMPLOYEE, {"email": email})

    def request(self, request_id):
        return self._first(REQUEST, {"request_id": request_id})

    def find_grant(self, requester, action, resource_id):
        return self._first(FIND_GRANT, {"requester": requester, "action": action, "resource_id": resource_id})

    def consume_grant(self, request_id, at):
        return bool(self._rows(CONSUME_GRANT, {"request_id": request_id, "at": at}, write=True))

    def sanctions_proximity(self, payment_id, hops):
        return self._first(SANCTIONS_PROXIMITY.format(control=CONTROL, hops=bounded(hops)), {"payment_id": payment_id})

    def inbound_near_threshold(self, payment_id, floor, threshold, window_days):
        return self._first(INBOUND_NEAR_THRESHOLD, {"payment_id": payment_id, "floor": floor, "threshold": threshold,
                                                    "window_days": int(window_days)})

    def case_subject_near(self, recipient, hops):
        return self._first(CASE_SUBJECT_NEAR.format(links=LINKS, hops=bounded(hops)), {"recipient": recipient})

    def case(self, case_id):
        return self._first(CASE, {"case_id": case_id})

    def linked(self, email, party_id, hops):
        return self._first(LINKED.format(links=LINKS, hops=bounded(hops)), {"email": email, "party_id": party_id})

    def deals_open_to(self, email, at):
        row = self._first(DEALS_OPEN_TO, {"email": email, "at": at})
        return sorted(set(row["deals"])) if row else []

    def ping(self):
        try:
            self._driver.verify_connectivity()
        except Exception:  # noqa: BLE001 - any failure means unhealthy
            return False
        return True
