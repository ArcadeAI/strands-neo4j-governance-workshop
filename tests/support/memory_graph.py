"""Larkspur Bank's graph in memory, from the same `seed.json` Neo4j is loaded from.

One `MemoryGraph` is both sides of the real deployment: `.book()` is the `Book` the Bank tools
write through, and the graph itself is the `Directory` the control plane reads. An approval Sana
records through the tools is the grant the gate finds on Pat's retry, and a crossing Cora
approves is the edge the gate reads on Ian's next call, exactly as when both talk to one Neo4j.

Each method mirrors one Cypher query in `mcp/bank_tools/graph.py` or `gate/bank_gate/directory.py`.
Path questions are a breadth-first search over the same relationship types the Cypher names.
"""

from __future__ import annotations

import copy
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from bank_graph import load_seed

CONTROL = ("HOLDS", "OWNS", "DIRECTOR_OF")
LINKS = ("HOLDS", "OWNS", "DIRECTOR_OF", "MANAGES", "IS")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _errors():
    from bank_tools.graph import Conflict, NotFound

    return NotFound, Conflict


class MemoryGraph:
    def __init__(self, seed: dict[str, Any] | None = None) -> None:
        seed = copy.deepcopy(seed or load_seed())
        self.employees = {e["email"]: e for e in seed["employees"]}
        self.parties = {p["id"]: {**p, "kind": "person"} for p in seed["people"]}
        self.parties |= {c["id"]: {**c, "kind": "company"} for c in seed["companies"]}
        for entry in seed["sanctions"]:
            self.parties[entry["entity"]] |= {"list_entry": entry["entry"], "list": entry["list"], "aliases": entry["aliases"],
                                              "program": entry["program"]}
        self.accounts = {a["id"]: a for a in seed["accounts"]}
        self.ownership = seed["ownership"]
        self.directors = seed["directors"]
        self.coverage = seed["coverage"]
        self.identities = seed["identities"]
        self.transfers = seed["transfers"]
        self.payments = {p["id"]: {**p, "decided_by": None, "decided_at": None, "hold_reason": None} for p in seed["payments"]}
        self.cases = {c["id"]: c for c in seed["cases"]}
        self.deals = {d["id"]: d for d in seed["deals"]}
        self.requests: dict[str, dict[str, Any]] = {}
        self.crossings: list[dict[str, Any]] = []
        self.sars: list[dict[str, Any]] = []
        self.healthy = True

    def book(self) -> MemoryBook:
        return MemoryBook(self)

    # The relationship graph the path questions walk.

    def edges(self, types: tuple[str, ...]) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        if "HOLDS" in types:
            found += [(a["holder"], a["id"]) for a in self.accounts.values()]
        if "OWNS" in types:
            found += [(o["owner"], o["company"]) for o in self.ownership]
        if "DIRECTOR_OF" in types:
            found += [(d["person"], d["company"]) for d in self.directors]
        if "MANAGES" in types:
            found += [(c["employee"], c["company"]) for c in self.coverage]
        if "IS" in types:
            found += [(i["employee"], i["person"]) for i in self.identities]
        return found

    def label(self, key: str) -> str:
        if key in self.employees:
            return self.employees[key]["name"]
        if key in self.parties:
            return self.parties[key]["name"]
        return key

    def shortest(self, start: str, goals: set[str], types: tuple[str, ...], hops: int) -> list[str] | None:
        """The nodes on a shortest undirected path from `start` to any of `goals`, at most `hops` long."""
        neighbours: dict[str, set[str]] = {}
        for a, b in self.edges(types):
            neighbours.setdefault(a, set()).add(b)
            neighbours.setdefault(b, set()).add(a)
        queue: deque[list[str]] = deque([[start]])
        seen = {start}
        while queue:
            path = queue.popleft()
            if len(path) - 1 >= hops:
                continue
            for nxt in sorted(neighbours.get(path[-1], ())):
                if nxt in seen:
                    continue
                if nxt in goals:
                    return [*path, nxt]
                seen.add(nxt)
                queue.append([*path, nxt])
        return None

    def path_answer(self, path: list[str] | None) -> dict[str, Any] | None:
        return None if path is None else {"hops": len(path) - 1, "chain": [self.label(k) for k in path]}

    def beneficiary(self, payment_id: str) -> dict[str, Any] | None:
        payment = self.payments.get(payment_id)
        return self.accounts[payment["to"]] if payment else None

    # Directory: what the gate reads.

    def employee(self, email: str) -> dict[str, Any] | None:
        e = self.employees.get(email)
        return {k: e[k] for k in ("email", "name", "role", "desk")} if e else None

    def request(self, request_id: str) -> dict[str, Any] | None:
        r = self.requests.get(request_id)
        return dict(r) if r else None

    def find_grant(self, requester: str, action: str, resource_id: str) -> dict[str, Any] | None:
        for r in sorted(self.requests.values(), key=lambda r: r.get("decided_at") or ""):
            if (
                r["requested_by"] == requester and r["action"] == action and r["resource_id"] == resource_id
                and r["status"] == "approved" and r.get("consumed_at") is None and r.get("decided_by") != requester
            ):
                return {"request_id": r["request_id"], "decided_by": r["decided_by"]}
        return None

    def consume_grant(self, request_id: str, at: str) -> bool:
        r = self.requests.get(request_id)
        if r is None or r["status"] != "approved" or r.get("consumed_at") is not None:
            return False
        r["consumed_at"] = at
        return True

    def sanctions_proximity(self, payment_id: str, hops: int) -> dict[str, Any] | None:
        account = self.beneficiary(payment_id)
        listed = {k for k, p in self.parties.items() if p.get("list_entry")}
        path = self.shortest(account["id"], listed, CONTROL, hops) if account else None
        if path is None:
            return None
        entity = self.parties[path[-1]]
        return {**self.path_answer(path), "entry": entity["list_entry"], "listed": entity["name"]}

    def inbound_near_threshold(self, payment_id: str, floor: float, threshold: float, window_days: int) -> dict[str, Any] | None:
        payment = self.payments.get(payment_id)
        if payment is None:
            return None
        end = _at(payment["created_at"])
        start = end - timedelta(days=window_days)
        hits = [t for t in self.transfers
                if t["to"] == payment["to"] and floor <= t["amount"] < threshold and start <= _at(t["at"]) <= end]
        holder = self.parties[self.accounts[payment["to"]]["holder"]]
        return {"amount": payment["amount"], "beneficiary": holder["name"], "count": len(hits),
                "senders": len({t["from"] for t in hits}), "total": sum(t["amount"] for t in hits)}

    def case_subject_near(self, recipient: str, hops: int) -> dict[str, Any] | None:
        employee = next((e for e in self.employees.values() if recipient in (e["email"], e.get("slack"))), None)
        if employee is None:
            return None
        found = []
        for case in self.cases.values():
            if case["status"] == "closed":
                continue
            path = self.shortest(employee["email"], {case["subject"]}, LINKS, hops)
            if path:
                found.append({"case_id": case["id"], "subject": self.parties[case["subject"]]["name"], **self.path_answer(path)})
        return min(found, key=lambda f: (f["hops"], f["case_id"])) if found else None

    def case(self, case_id: str) -> dict[str, Any] | None:
        c = self.cases.get(case_id)
        if c is None:
            return None
        return {"case_id": c["id"], "owner": c["owner"], "status": c["status"], "subject_id": c["subject"],
                "subject": self.parties[c["subject"]]["name"]}

    def linked(self, email: str, party_id: str, hops: int) -> dict[str, Any] | None:
        if email not in self.employees or party_id not in self.parties:
            return None
        return self.path_answer(self.shortest(email, {party_id}, LINKS, hops))

    def deals_open_to(self, email: str, at: str) -> list[str]:
        insider = {d["id"] for d in self.deals.values() if email in d["insiders"]}
        crossed = {c["deal_id"] for c in self.crossings if c["email"] == email and c["expires_at"] > at}
        return sorted(insider | crossed)

    def ping(self) -> bool:
        return self.healthy


class MemoryBook:
    """`Book` over a `MemoryGraph`."""

    def __init__(self, graph: MemoryGraph) -> None:
        self.graph = graph

    def _account_view(self, account_id: str) -> dict[str, Any]:
        a = self.graph.accounts[account_id]
        return {"account_id": a["id"], "account_number": a["number"], "bank": a["bank"],
                "holder": self.graph.parties[a["holder"]]["name"], "holder_id": a["holder"]}

    async def payment_exceptions(self):
        rows = [
            {"payment_id": p["id"], "amount": p["amount"], "currency": p["currency"],
             "originator": self._account_view(p["from"])["holder"], "beneficiary": self._account_view(p["to"])["holder"],
             "alert": p["alert"], "created_at": p["created_at"], "status": p["status"]}
            for p in self.graph.payments.values() if p["status"] == "pending_review"
        ]
        return sorted(rows, key=lambda r: r["created_at"])

    async def get_payment(self, payment_id):
        NotFound, _ = _errors()
        p = self.graph.payments.get(payment_id)
        if p is None:
            raise NotFound(payment_id)
        return {"payment_id": p["id"], "amount": p["amount"], "currency": p["currency"], "status": p["status"],
                "created_at": p["created_at"], "alert": p["alert"], "reference": p["reference"],
                "originator": self._account_view(p["from"]), "beneficiary": self._account_view(p["to"]),
                "decided_by": p["decided_by"], "decided_at": p["decided_at"], "hold_reason": p["hold_reason"]}

    async def screen_party(self, name):
        key = name.strip().lower()
        listed = [
            {"entry": p["list_entry"], "list": p["list"], "name": p["name"], "program": p["program"]}
            for p in self.graph.parties.values()
            if p.get("list_entry") and (p["name"].lower() == key or key in [a.lower() for a in p["aliases"]])
        ]
        pep = [{"name": p["name"], "detail": p["pep_detail"]} for p in self.graph.parties.values()
               if p["kind"] == "person" and p.get("pep") and p["name"].lower() == key]
        return {"list_matches": sorted(listed, key=lambda r: r["entry"]), "pep_matches": pep}

    async def set_payment_status(self, payment_id, status, actor, reason):
        NotFound, Conflict = _errors()
        p = self.graph.payments.get(payment_id)
        if p is None:
            raise NotFound(payment_id)
        if p["status"] != "pending_review":
            raise Conflict(f"{payment_id} is already {p['status']}.")
        p.update(status=status, decided_by=actor, decided_at=_now(), hold_reason=reason)

    async def get_case(self, case_id):
        NotFound, _ = _errors()
        c = self.graph.cases.get(case_id)
        if c is None:
            raise NotFound(case_id)
        s = self.graph.parties[c["subject"]]
        accounts = sorted((a for a in self.graph.accounts.values() if a["holder"] == s["id"]), key=lambda a: a["id"])
        return {"case_id": c["id"], "status": c["status"], "opened_at": c["opened_at"], "alert": c["alert"], "owner": c["owner"],
                "subject": {"party_id": s["id"], "name": s["name"], "dob": s.get("dob"), "ssn": s.get("ssn"), "pep": s.get("pep"),
                            "pep_detail": s.get("pep_detail")},
                "accounts": [{"account_id": a["id"], "account_number": a["number"], "bank": a["bank"], "status": a["status"]}
                             for a in accounts]}

    async def trace_funds(self, account_id, hops):
        NotFound, _ = _errors()
        if account_id not in self.graph.accounts:
            raise NotFound(account_id)
        from bank_tools.graph import clamp_hops

        limit = clamp_hops(hops)
        paths: list[list[dict[str, Any]]] = []

        def extend(path: list[dict[str, Any]], at: str) -> None:
            for t in self.graph.transfers:
                if t["from"] != at or any(step["id"] == t["id"] for step in path):
                    continue
                step = {"id": t["id"], "from": t["from"], "to": t["to"], "amount": t["amount"], "at": t["at"]}
                paths.append([*path, step])
                if len(path) + 1 < limit:
                    extend([*path, step], t["to"])

        extend([], account_id)
        return paths

    def _owner_paths(self, start: str, down: bool) -> list[tuple[list[str], list[float]]]:
        found: list[tuple[list[str], list[float]]] = []

        def walk(chain: list[str], pcts: list[float]) -> None:
            if len(chain) > 4:
                return
            here = chain[-1] if down else chain[0]
            for o in self.graph.ownership:
                nxt = o["company"] if down and o["owner"] == here else o["owner"] if not down and o["company"] == here else None
                if nxt is None or nxt in chain:
                    continue
                new_chain = [*chain, nxt] if down else [nxt, *chain]
                new_pcts = [*pcts, o["pct"]] if down else [o["pct"], *pcts]
                found.append((new_chain, new_pcts))
                walk(new_chain, new_pcts)

        walk([start], [])
        return found

    async def trace_ownership(self, party_id):
        NotFound, _ = _errors()
        p = self.graph.parties.get(party_id)
        if p is None:
            raise NotFound(party_id)
        name = self.graph.label
        owns = [{"company_id": chain[-1], "name": name(chain[-1]), "list_entry": self.graph.parties[chain[-1]].get("list_entry"),
                 "pcts": pcts, "chain": [name(k) for k in chain]} for chain, pcts in self._owner_paths(party_id, down=True)]
        owned_by = [{"party_id": chain[0], "name": name(chain[0]), "list_entry": self.graph.parties[chain[0]].get("list_entry"),
                     "pep": self.graph.parties[chain[0]].get("pep"), "pcts": pcts, "chain": [name(k) for k in chain]}
                    for chain, pcts in self._owner_paths(party_id, down=False)]
        return {
            "party_id": p["id"], "name": p["name"], "kind": p["kind"], "pep": p.get("pep"), "list_entry": p.get("list_entry"),
            "owns": owns, "owned_by": owned_by,
            "director_of": [{"company_id": d["company"], "name": name(d["company"]),
                             "list_entry": self.graph.parties[d["company"]].get("list_entry")}
                            for d in self.graph.directors if d["person"] == party_id],
            "directors": [{"party_id": d["person"], "name": name(d["person"]), "pep": self.graph.parties[d["person"]].get("pep")}
                          for d in self.graph.directors if d["company"] == party_id],
            "accounts": [{"account_id": a["id"], "account_number": a["number"], "bank": a["bank"], "status": a["status"]}
                         for a in self.graph.accounts.values() if a["holder"] == party_id],
        }

    async def freeze_account(self, account_id, case_id, reason, actor):
        NotFound, Conflict = _errors()
        account = self.graph.accounts.get(account_id)
        if account is None:
            raise NotFound(account_id)
        if case_id not in self.graph.cases:
            raise NotFound(case_id)
        if account["status"] != "open":
            raise Conflict(f"{account_id} is already {account['status']}.")
        account.update(status="frozen", frozen_by=actor, frozen_at=_now(), freeze_reason=reason, freeze_case=case_id)

    async def file_sar(self, case_id, narrative, actor):
        NotFound, Conflict = _errors()
        case = self.graph.cases.get(case_id)
        if case is None:
            raise NotFound(case_id)
        if case["status"] != "open":
            raise Conflict(f"{case_id} is {case['status']}; a SAR can only be filed on an open case.")
        case["status"] = "sar_filed"
        sar = {"sar_id": f"SAR-{len(self.graph.sars) + 1:08d}", "filed_at": _now(), "filed_by": actor}
        self.graph.sars.append({**sar, "case_id": case_id, "narrative": narrative})
        return sar

    async def search_companies(self, query):
        key = query.strip().lower()
        rows = [{"company_id": c["id"], "name": c["name"], "industry": c["industry"], "hq": c["hq"]}
                for c in self.graph.parties.values()
                if c["kind"] == "company" and (key in c["name"].lower() or key in (c.get("industry") or "").lower())]
        return sorted(rows, key=lambda r: r["name"])

    async def company_profile(self, company_id):
        NotFound, _ = _errors()
        c = self.graph.parties.get(company_id)
        if c is None or c["kind"] != "company":
            raise NotFound(company_id)
        deals = []
        for d in sorted(self.graph.deals.values(), key=lambda d: d["id"]):
            for role, other in (("target", "acquirer"), ("acquirer", "target")):
                if d[role] == company_id:
                    deals.append({"deal_id": d["id"], "codename": d["codename"], "role": role,
                                  "counterparty": self.graph.label(d[other]) if d[other] else None,
                                  "stage": d["stage"], "valuation": d["valuation"], "terms": d["terms"]})
        return {
            "company_id": c["id"], "name": c["name"], "industry": c["industry"], "hq": c["hq"],
            "annual_revenue": c["annual_revenue"], "public_profile": c["public_profile"],
            "coverage": sorted(self.graph.employees[x["employee"]]["name"] for x in self.graph.coverage if x["company"] == company_id),
            "owners": [{"name": self.graph.label(o["owner"]), "pct": o["pct"]} for o in self.graph.ownership if o["company"] == company_id],
            "deals": deals,
        }

    def _deal(self, d: dict[str, Any]) -> dict[str, Any]:
        return {"deal_id": d["id"], "codename": d["codename"], "target": self.graph.label(d["target"]),
                "acquirer": self.graph.label(d["acquirer"]) if d["acquirer"] else None, "stage": d["stage"],
                "valuation": d["valuation"], "terms": d["terms"]}

    async def list_deals(self):
        return [self._deal(d) for d in sorted(self.graph.deals.values(), key=lambda d: d["id"])]

    async def get_deal(self, deal_id):
        NotFound, _ = _errors()
        d = self.graph.deals.get(deal_id)
        if d is None:
            raise NotFound(deal_id)
        return {**self._deal(d), "insiders": [self.graph.employees[e]["name"] for e in d["insiders"]]}

    async def employee(self, email):
        return self.graph.employee(email)

    async def approvers(self, roles):
        found = [e for e in self.graph.employees.values() if e["role"] in roles]
        return [self.graph.employee(e["email"]) for e in sorted(found, key=lambda e: (e["rota"], e["email"]))]

    async def case(self, case_id):
        return self.graph.case(case_id)

    async def linked(self, email, party_id, hops):
        return self.graph.linked(email, party_id, hops)

    async def open_request(self, action, resource_id, requester):
        for r in self.graph.requests.values():
            if (r["action"], r["resource_id"], r["requested_by"], r["status"]) == (action, resource_id, requester, "pending"):
                return dict(r)
        return None

    async def create_request(self, request):
        NotFound, _ = _errors()
        if request["requested_by"] not in self.graph.employees:
            raise NotFound(request["requested_by"])
        stored = {**request, "status": "pending", "decided_by": None, "decided_at": None, "note": None, "consumed_at": None,
                  "expires_at": None}
        self.graph.requests[request["request_id"]] = stored
        return dict(stored)

    async def get_request(self, request_id):
        NotFound, _ = _errors()
        if request_id not in self.graph.requests:
            raise NotFound(request_id)
        return dict(self.graph.requests[request_id])

    async def list_requests(self, user, status):
        rows = [dict(r) for r in self.graph.requests.values()
                if user in (r["requested_by"], r["routed_to"]) and (status is None or r["status"] == status)]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    async def decide_request(self, request_id, decision, note, actor, expires_at):
        _, Conflict = _errors()
        current = await self.get_request(request_id)
        if current["status"] != "pending":
            raise Conflict(f"{request_id} is already {current['status']}.")
        self.graph.requests[request_id].update(status=decision, decided_by=actor, decided_at=_now(), note=note, expires_at=expires_at)
        return dict(self.graph.requests[request_id])

    async def cross_wall(self, email, deal_id, expires_at, approved_by, request_id):
        NotFound, _ = _errors()
        if deal_id not in self.graph.deals:
            raise NotFound(deal_id)
        self.graph.crossings = [c for c in self.graph.crossings if not (c["email"] == email and c["deal_id"] == deal_id)]
        self.graph.crossings.append({"email": email, "deal_id": deal_id, "expires_at": expires_at, "approved_by": approved_by,
                                     "request_id": request_id, "granted_at": _now()})
