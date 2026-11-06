"""Where the bank's data lives: one Neo4j graph, reached with the server's own secrets.

The tools never see a connection string or a password. `arcade deploy` uploads NEO4J_URI,
NEO4J_USERNAME and NEO4J_PASSWORD from `mcp/.env` as Arcade secrets, and each call reads
them from its context. The model and the agent's laptop never hold them.

Every query is fixed. A value a caller supplied goes in as a parameter, never into the query
text. The one exception is a path length (`*..3`), which Cypher does not accept as a
parameter: it is an int the tool clamps to a small range before it is formatted in.

`Book` is the whole data interface the tools use. `Neo4jBook` is the real one; the tests swap
in an in-memory graph through `use_book`.
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

LINKS = "HOLDS|OWNS|DIRECTOR_OF|MANAGES|IS"
MAX_HOPS = 5


class NotFound(LookupError):
    """No node with that id."""


class Conflict(ValueError):
    """The node is not in a state the write allows, such as a payment that was already released."""


class Book(Protocol):
    async def payment_exceptions(self) -> list[dict[str, Any]]: ...
    async def get_payment(self, payment_id: str) -> dict[str, Any]: ...
    async def screen_party(self, name: str) -> dict[str, Any]: ...
    async def set_payment_status(self, payment_id: str, status: str, actor: str, reason: str | None) -> None: ...
    async def get_case(self, case_id: str) -> dict[str, Any]: ...
    async def trace_funds(self, account_id: str, hops: int) -> list[list[dict[str, Any]]]: ...
    async def trace_ownership(self, party_id: str) -> dict[str, Any]: ...
    async def freeze_account(self, account_id: str, case_id: str, reason: str, actor: str) -> None: ...
    async def file_sar(self, case_id: str, narrative: str, actor: str) -> dict[str, Any]: ...
    async def search_companies(self, query: str) -> list[dict[str, Any]]: ...
    async def company_profile(self, company_id: str) -> dict[str, Any]: ...
    async def list_deals(self) -> list[dict[str, Any]]: ...
    async def get_deal(self, deal_id: str) -> dict[str, Any]: ...
    async def employee(self, email: str) -> dict[str, Any] | None: ...
    async def approvers(self, roles: list[str]) -> list[dict[str, Any]]: ...
    async def case(self, case_id: str) -> dict[str, Any] | None: ...
    async def linked(self, email: str, party_id: str, hops: int) -> dict[str, Any] | None: ...
    async def open_request(self, action: str, resource_id: str, requester: str) -> dict[str, Any] | None: ...
    async def create_request(self, request: dict[str, Any]) -> dict[str, Any]: ...
    async def get_request(self, request_id: str) -> dict[str, Any]: ...
    async def list_requests(self, user: str, status: str | None) -> list[dict[str, Any]]: ...
    async def decide_request(self, request_id: str, decision: str, note: str | None, actor: str, expires_at: str | None) -> dict[str, Any]: ...
    async def cross_wall(self, email: str, deal_id: str, expires_at: str, approved_by: str, request_id: str) -> None: ...


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def clamp_hops(hops: int) -> int:
    return max(1, min(int(hops), MAX_HOPS))


ACCOUNT_VIEW = "{{account_id: {a}.id, account_number: {a}.number, bank: {a}.bank, holder: {h}.name, holder_id: {h}.id}}"

PAYMENT_EXCEPTIONS = """
MATCH (p:Payment {status: 'pending_review'})-[:FROM]->(:Account)<-[:HOLDS]-(oh:Party),
      (p)-[:TO]->(:Account)<-[:HOLDS]-(bh:Party)
RETURN p.id AS payment_id, p.amount AS amount, p.currency AS currency, oh.name AS originator,
       bh.name AS beneficiary, p.alert AS alert, p.created_at AS created_at, p.status AS status
ORDER BY p.created_at
"""

GET_PAYMENT = f"""
MATCH (p:Payment {{id: $payment_id}})-[:FROM]->(oa:Account)<-[:HOLDS]-(oh:Party),
      (p)-[:TO]->(ba:Account)<-[:HOLDS]-(bh:Party)
RETURN p.id AS payment_id, p.amount AS amount, p.currency AS currency, p.status AS status,
       p.created_at AS created_at, p.alert AS alert, p.reference AS reference,
       {ACCOUNT_VIEW.format(a="oa", h="oh")} AS originator,
       {ACCOUNT_VIEW.format(a="ba", h="bh")} AS beneficiary,
       p.decided_by AS decided_by, p.decided_at AS decided_at, p.hold_reason AS hold_reason
"""

SCREEN_LIST = """
MATCH (s:Sanctioned)
WHERE toLower(s.name) = toLower($name) OR any(alias IN s.aliases WHERE toLower(alias) = toLower($name))
RETURN s.list_entry AS entry, s.list AS list, s.name AS name, s.program AS program
ORDER BY entry
"""

SCREEN_PEP = """
MATCH (p:Person {pep: true})
WHERE toLower(p.name) = toLower($name)
RETURN p.name AS name, p.pep_detail AS detail
"""

SET_PAYMENT = """
MATCH (p:Payment {id: $payment_id})
WHERE p.status = 'pending_review'
SET p.status = $status, p.decided_by = $actor, p.decided_at = $at, p.hold_reason = $reason
RETURN p.id AS id
"""

PAYMENT_STATUS = "MATCH (p:Payment {id: $payment_id}) RETURN p.status AS status"

GET_CASE = """
MATCH (c:Case {id: $case_id})-[:SUBJECT]->(s:Party)
OPTIONAL MATCH (s)-[:HOLDS]->(a:Account)
WITH c, s, a ORDER BY a.id
RETURN c.id AS case_id, c.status AS status, c.opened_at AS opened_at, c.alert AS alert, c.owner AS owner,
       {party_id: s.id, name: s.name, dob: s.dob, ssn: s.ssn, pep: s.pep, pep_detail: s.pep_detail} AS subject,
       [x IN collect(a) WHERE x IS NOT NULL | {account_id: x.id, account_number: x.number, bank: x.bank, status: x.status}] AS accounts
"""

TRACE_FUNDS = """
MATCH path = (:Account {{id: $account_id}})-[:PAID*1..{hops}]->(:Account)
RETURN [r IN relationships(path) | {{id: r.id, from: startNode(r).id, to: endNode(r).id, amount: r.amount, at: r.at}}] AS steps
"""

ACCOUNT_EXISTS = "MATCH (a:Account {id: $account_id}) RETURN a.id AS id"

PARTY = """
MATCH (p:Party {id: $party_id})
RETURN p.id AS party_id, p.name AS name, CASE WHEN p:Person THEN 'person' ELSE 'company' END AS kind,
       p.pep AS pep, p.list_entry AS list_entry
"""

OWNS_DOWN = """
MATCH path = (:Party {id: $party_id})-[:OWNS*1..4]->(c:Company)
RETURN c.id AS company_id, c.name AS name, c.list_entry AS list_entry,
       [r IN relationships(path) | r.pct] AS pcts, [n IN nodes(path) | n.name] AS chain
"""

OWNED_BY = """
MATCH path = (o:Party)-[:OWNS*1..4]->(:Party {id: $party_id})
RETURN o.id AS party_id, o.name AS name, o.list_entry AS list_entry, o.pep AS pep,
       [r IN relationships(path) | r.pct] AS pcts, [n IN nodes(path) | n.name] AS chain
"""

DIRECTORSHIPS = """
MATCH (p:Party {id: $party_id})
OPTIONAL MATCH (p)-[:DIRECTOR_OF]->(c:Company)
OPTIONAL MATCH (d:Person)-[:DIRECTOR_OF]->(p)
OPTIONAL MATCH (p)-[:HOLDS]->(a:Account)
RETURN [x IN collect(DISTINCT c) WHERE x IS NOT NULL | {company_id: x.id, name: x.name, list_entry: x.list_entry}] AS director_of,
       [x IN collect(DISTINCT d) WHERE x IS NOT NULL | {party_id: x.id, name: x.name, pep: x.pep}] AS directors,
       [x IN collect(DISTINCT a) WHERE x IS NOT NULL | {account_id: x.id, account_number: x.number, bank: x.bank, status: x.status}] AS accounts
"""

FREEZE = """
MATCH (a:Account {id: $account_id}), (c:Case {id: $case_id})
WHERE a.status = 'open'
SET a.status = 'frozen', a.frozen_by = $actor, a.frozen_at = $at, a.freeze_reason = $reason, a.freeze_case = $case_id
MERGE (c)-[:FROZE]->(a)
RETURN a.id AS id
"""

ACCOUNT_STATUS = "MATCH (a:Account {id: $account_id}) OPTIONAL MATCH (c:Case {id: $case_id}) RETURN a.status AS status, c.id AS case_id"

FILE_SAR = """
MATCH (c:Case {id: $case_id})
WHERE c.status = 'open'
SET c.status = 'sar_filed'
CREATE (s:Sar {id: $sar_id, filed_at: $at, filed_by: $actor, narrative: $narrative})-[:FOR]->(c)
RETURN s.id AS sar_id, s.filed_at AS filed_at, s.filed_by AS filed_by
"""

CASE_STATUS = "MATCH (c:Case {id: $case_id}) RETURN c.status AS status"

SEARCH_COMPANIES = """
MATCH (c:Company)
WHERE toLower(c.name) CONTAINS toLower($query) OR toLower(coalesce(c.industry, '')) CONTAINS toLower($query)
RETURN c.id AS company_id, c.name AS name, c.industry AS industry, c.hq AS hq
ORDER BY c.name
"""

PROFILE = """
MATCH (c:Company {id: $company_id})
OPTIONAL MATCH (rm:Employee)-[:MANAGES]->(c)
OPTIONAL MATCH (o:Party)-[x:OWNS]->(c)
WITH c, collect(DISTINCT rm.name) AS coverage, [y IN collect(DISTINCT {name: o.name, pct: x.pct}) WHERE y.name IS NOT NULL] AS owners
OPTIONAL MATCH (d:Deal)-[role:TARGET|ACQUIRER]->(c)
OPTIONAL MATCH (d)-[other:TARGET|ACQUIRER]->(cp:Company) WHERE cp <> c
WITH c, coverage, owners, d, role, cp ORDER BY d.id
RETURN c.id AS company_id, c.name AS name, c.industry AS industry, c.hq AS hq, c.annual_revenue AS annual_revenue,
       c.public_profile AS public_profile, coverage, owners,
       [x IN collect(CASE WHEN d IS NULL THEN null ELSE {deal_id: d.id, codename: d.codename, role: toLower(type(role)),
         counterparty: cp.name, stage: d.stage, valuation: d.valuation, terms: d.terms} END) WHERE x IS NOT NULL] AS deals
"""

DEAL_FIELDS = """
d.id AS deal_id, d.codename AS codename, t.name AS target, a.name AS acquirer, d.stage AS stage,
d.valuation AS valuation, d.terms AS terms
"""

LIST_DEALS = f"""
MATCH (d:Deal)-[:TARGET]->(t:Company)
OPTIONAL MATCH (d)-[:ACQUIRER]->(a:Company)
RETURN {DEAL_FIELDS}
ORDER BY d.id
"""

GET_DEAL = f"""
MATCH (d:Deal {{id: $deal_id}})-[:TARGET]->(t:Company)
OPTIONAL MATCH (d)-[:ACQUIRER]->(a:Company)
OPTIONAL MATCH (i:Employee)-[:INSIDER_ON]->(d)
RETURN {DEAL_FIELDS}, collect(i.name) AS insiders
"""

EMPLOYEE = "MATCH (e:Employee {email: $email}) RETURN e.email AS email, e.name AS name, e.role AS role, e.desk AS desk"

APPROVERS = """
MATCH (e:Employee)
WHERE e.role IN $roles
RETURN e.email AS email, e.name AS name, e.role AS role, e.desk AS desk
ORDER BY e.rota, e.email
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

REQUEST_FIELDS = """
r.id AS request_id, r.action AS action, r.resource_id AS resource_id, r.case_id AS case_id,
r.justification AS justification, r.status AS status, r.requested_by AS requested_by,
r.routed_to AS routed_to, r.created_at AS created_at, r.decided_by AS decided_by,
r.decided_at AS decided_at, r.note AS note, r.consumed_at AS consumed_at, r.expires_at AS expires_at
"""

OPEN_REQUEST = f"""
MATCH (r:ApprovalRequest {{action: $action, resource_id: $resource_id, requested_by: $requester, status: 'pending'}})
RETURN {REQUEST_FIELDS}
LIMIT 1
"""

CREATE_REQUEST = f"""
MATCH (req:Employee {{email: $requested_by}})
OPTIONAL MATCH (ap:Employee {{email: $routed_to}})
CREATE (r:ApprovalRequest {{id: $request_id, action: $action, resource_id: $resource_id, case_id: $case_id,
                            justification: $justification, status: 'pending', requested_by: $requested_by,
                            routed_to: $routed_to, created_at: $created_at}})
CREATE (req)-[:REQUESTED]->(r)
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
SET r.status = $decision, r.decided_by = $actor, r.decided_at = $at, r.note = $note, r.expires_at = $expires_at
WITH r
OPTIONAL MATCH (e:Employee {{email: $actor}})
FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END | MERGE (e)-[:DECIDED]->(r))
RETURN {REQUEST_FIELDS}
"""

CROSS_WALL = """
MATCH (e:Employee {email: $email}), (d:Deal {id: $deal_id})
MERGE (e)-[w:WALL_CROSSED]->(d)
SET w.expires_at = $expires_at, w.approved_by = $approved_by, w.request_id = $request_id, w.granted_at = $at
RETURN d.id AS id
"""


class Neo4jBook:
    """`Book` over a Neo4j async driver."""

    def __init__(self, driver: Any, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    async def _rows(self, query: str, params: dict[str, Any], *, write: bool = False) -> list[dict[str, Any]]:
        from neo4j import RoutingControl

        records, _, _ = await self._driver.execute_query(
            query, params, database_=self._database, routing_=RoutingControl.WRITE if write else RoutingControl.READ
        )
        return [dict(r) for r in records]

    async def _one(self, query: str, params: dict[str, Any], missing: str) -> dict[str, Any]:
        rows = await self._rows(query, params)
        if not rows:
            raise NotFound(missing)
        return rows[0]

    async def payment_exceptions(self):
        return await self._rows(PAYMENT_EXCEPTIONS, {})

    async def get_payment(self, payment_id):
        return await self._one(GET_PAYMENT, {"payment_id": payment_id}, payment_id)

    async def screen_party(self, name):
        return {
            "list_matches": await self._rows(SCREEN_LIST, {"name": name.strip()}),
            "pep_matches": await self._rows(SCREEN_PEP, {"name": name.strip()}),
        }

    async def set_payment_status(self, payment_id, status, actor, reason):
        params = {"payment_id": payment_id, "status": status, "actor": actor, "at": now(), "reason": reason}
        if await self._rows(SET_PAYMENT, params, write=True):
            return
        current = await self._one(PAYMENT_STATUS, {"payment_id": payment_id}, payment_id)
        raise Conflict(f"{payment_id} is already {current['status']}.")

    async def get_case(self, case_id):
        return await self._one(GET_CASE, {"case_id": case_id}, case_id)

    async def trace_funds(self, account_id, hops):
        rows = await self._rows(TRACE_FUNDS.format(hops=clamp_hops(hops)), {"account_id": account_id})
        if not rows:
            await self._one(ACCOUNT_EXISTS, {"account_id": account_id}, account_id)
        return [r["steps"] for r in rows]

    async def trace_ownership(self, party_id):
        party = await self._one(PARTY, {"party_id": party_id}, party_id)
        links = (await self._rows(DIRECTORSHIPS, {"party_id": party_id}))[0]
        return {
            **party,
            "owns": await self._rows(OWNS_DOWN, {"party_id": party_id}),
            "owned_by": await self._rows(OWNED_BY, {"party_id": party_id}),
            **links,
        }

    async def freeze_account(self, account_id, case_id, reason, actor):
        params = {"account_id": account_id, "case_id": case_id, "reason": reason, "actor": actor, "at": now()}
        if await self._rows(FREEZE, params, write=True):
            return
        current = await self._one(ACCOUNT_STATUS, {"account_id": account_id, "case_id": case_id}, account_id)
        if current["case_id"] is None:
            raise NotFound(case_id)
        raise Conflict(f"{account_id} is already {current['status']}.")

    async def file_sar(self, case_id, narrative, actor):
        params = {"case_id": case_id, "narrative": narrative, "actor": actor, "at": now(), "sar_id": new_id("SAR")}
        rows = await self._rows(FILE_SAR, params, write=True)
        if rows:
            return rows[0]
        current = await self._one(CASE_STATUS, {"case_id": case_id}, case_id)
        raise Conflict(f"{case_id} is {current['status']}; a SAR can only be filed on an open case.")

    async def search_companies(self, query):
        return await self._rows(SEARCH_COMPANIES, {"query": query.strip()})

    async def company_profile(self, company_id):
        return await self._one(PROFILE, {"company_id": company_id}, company_id)

    async def list_deals(self):
        return await self._rows(LIST_DEALS, {})

    async def get_deal(self, deal_id):
        return await self._one(GET_DEAL, {"deal_id": deal_id}, deal_id)

    async def employee(self, email):
        rows = await self._rows(EMPLOYEE, {"email": email})
        return rows[0] if rows else None

    async def approvers(self, roles):
        return await self._rows(APPROVERS, {"roles": list(roles)})

    async def case(self, case_id):
        rows = await self._rows(CASE, {"case_id": case_id})
        return rows[0] if rows else None

    async def linked(self, email, party_id, hops):
        rows = await self._rows(LINKED.format(links=LINKS, hops=clamp_hops(hops)), {"email": email, "party_id": party_id})
        return rows[0] if rows else None

    async def open_request(self, action, resource_id, requester):
        rows = await self._rows(OPEN_REQUEST, {"action": action, "resource_id": resource_id, "requester": requester})
        return rows[0] if rows else None

    async def create_request(self, request):
        rows = await self._rows(CREATE_REQUEST, request, write=True)
        if not rows:
            raise NotFound(request["requested_by"])
        return rows[0]

    async def get_request(self, request_id):
        return await self._one(GET_REQUEST, {"request_id": request_id}, request_id)

    async def list_requests(self, user, status):
        return await self._rows(LIST_REQUESTS, {"user": user, "status": status})

    async def decide_request(self, request_id, decision, note, actor, expires_at):
        params = {"request_id": request_id, "decision": decision, "note": note, "actor": actor, "at": now(), "expires_at": expires_at}
        rows = await self._rows(DECIDE_REQUEST, params, write=True)
        if rows:
            return rows[0]
        current = await self.get_request(request_id)
        raise Conflict(f"{request_id} is already {current['status']}.")

    async def cross_wall(self, email, deal_id, expires_at, approved_by, request_id):
        params = {"email": email, "deal_id": deal_id, "expires_at": expires_at, "approved_by": approved_by,
                  "request_id": request_id, "at": now()}
        if not await self._rows(CROSS_WALL, params, write=True):
            raise NotFound(deal_id)


_drivers: dict[tuple[str, str], Any] = {}
_override: Callable[[Any], Book] | None = None


def use_book(factory: Callable[[Any], Book] | None) -> None:
    """Make every tool use `factory(context)` instead of Neo4j; `None` puts Neo4j back."""
    global _override
    _override = factory


def book_for(context: Any) -> Book:
    """The graph this call reads and writes, from the call's own secrets."""
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
    return Neo4jBook(driver, os.environ.get("NEO4J_DATABASE", "").strip() or "neo4j")
