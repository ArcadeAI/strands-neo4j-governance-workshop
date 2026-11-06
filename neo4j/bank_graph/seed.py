"""Load Bowser Capital's graph into Neo4j, print it as Cypher, and look at the staff in it.

    uv run seed              # load seed.json into the database NEO4J_URI names
    uv run seed --reset      # delete the workshop's nodes first, then load
    uv run seed --print      # print the same graph as one Cypher script (neo4j/seed.cypher)

    uv run staff list
    uv run staff set-role ian@bank.example mna_banker

The employees are the people the control plane governs. Their role lives in the graph next to
the customers, accounts, cases and deals, and the gate reads it on every call, so changing a
role here changes what the policy allows on the next tool call, with no restart.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from importlib import resources
from typing import Any

LABELS = ["Employee", "Party", "Person", "Company", "Account", "Payment", "Case", "Deal", "ApprovalRequest", "Sar"]

CONSTRAINTS = [
    "CREATE CONSTRAINT employee_email IF NOT EXISTS FOR (e:Employee) REQUIRE e.email IS UNIQUE",
    "CREATE CONSTRAINT party_id IF NOT EXISTS FOR (p:Party) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT account_id IF NOT EXISTS FOR (a:Account) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT payment_id IF NOT EXISTS FOR (p:Payment) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT case_id IF NOT EXISTS FOR (c:Case) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT deal_id IF NOT EXISTS FOR (d:Deal) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT approval_id IF NOT EXISTS FOR (r:ApprovalRequest) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT sar_id IF NOT EXISTS FOR (s:Sar) REQUIRE s.id IS UNIQUE",
]

RESET = "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) DETACH DELETE n"

EMPLOYEES = """
UNWIND $rows AS r
MERGE (e:Employee {email: r.email})
SET e.name = r.name, e.role = r.role, e.desk = r.desk, e.slack = r.slack, e.rota = r.rota
"""

PEOPLE = """
UNWIND $rows AS r
MERGE (p:Party:Person {id: r.id})
SET p.name = r.name, p.dob = r.dob, p.ssn = r.ssn, p.pep = r.pep, p.pep_detail = r.pep_detail
"""

COMPANIES = """
UNWIND $rows AS r
MERGE (c:Party:Company {id: r.id})
SET c.name = r.name, c.ein = r.ein, c.industry = r.industry, c.hq = r.hq,
    c.annual_revenue = r.annual_revenue, c.public_profile = r.public_profile
"""

SANCTIONS = """
UNWIND $rows AS r
MATCH (p:Party {id: r.entity})
SET p:Sanctioned, p.list_entry = r.entry, p.list = r.list, p.aliases = r.aliases, p.program = r.program
"""

ACCOUNTS = """
UNWIND $rows AS r
MATCH (h:Party {id: r.holder})
MERGE (a:Account {id: r.id})
SET a.number = r.number, a.bank = r.bank, a.kind = r.kind, a.status = r.status
MERGE (h)-[:HOLDS]->(a)
"""

OWNERSHIP = """
UNWIND $rows AS r
MATCH (o:Party {id: r.owner}), (c:Company {id: r.company})
MERGE (o)-[x:OWNS]->(c)
SET x.pct = r.pct
"""

DIRECTORS = """
UNWIND $rows AS r
MATCH (p:Person {id: r.person}), (c:Company {id: r.company})
MERGE (p)-[:DIRECTOR_OF]->(c)
"""

COVERAGE = """
UNWIND $rows AS r
MATCH (e:Employee {email: r.employee}), (c:Company {id: r.company})
MERGE (e)-[:MANAGES]->(c)
"""

IDENTITIES = """
UNWIND $rows AS r
MATCH (e:Employee {email: r.employee}), (p:Person {id: r.person})
MERGE (e)-[:IS]->(p)
"""

TRANSFERS = """
UNWIND $rows AS r
MATCH (a:Account {id: r.from}), (b:Account {id: r.to})
MERGE (a)-[t:PAID {id: r.id}]->(b)
SET t.amount = r.amount, t.at = r.at
"""

PAYMENTS = """
UNWIND $rows AS r
MATCH (a:Account {id: r.from}), (b:Account {id: r.to})
MERGE (p:Payment {id: r.id})
SET p.amount = r.amount, p.currency = r.currency, p.created_at = r.created_at, p.status = r.status,
    p.alert = r.alert, p.reference = r.reference
MERGE (p)-[:FROM]->(a)
MERGE (p)-[:TO]->(b)
"""

CASES = """
UNWIND $rows AS r
MATCH (s:Party {id: r.subject}), (o:Employee {email: r.owner})
MERGE (c:Case {id: r.id})
SET c.status = r.status, c.opened_at = r.opened_at, c.alert = r.alert, c.owner = r.owner
MERGE (c)-[:SUBJECT]->(s)
MERGE (c)-[:ASSIGNED_TO]->(o)
"""

DEALS = """
UNWIND $rows AS r
MATCH (t:Company {id: r.target})
MERGE (d:Deal {id: r.id})
SET d.codename = r.codename, d.stage = r.stage, d.valuation = r.valuation, d.terms = r.terms
MERGE (d)-[:TARGET]->(t)
WITH d, r
OPTIONAL MATCH (a:Company {id: r.acquirer})
FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END | MERGE (d)-[:ACQUIRER]->(a))
WITH d, r
UNWIND r.insiders AS email
MATCH (e:Employee {email: email})
MERGE (e)-[:INSIDER_ON]->(d)
"""


def load_seed() -> dict[str, Any]:
    """The graph as `seed.json` holds it."""
    return json.loads(resources.files("bank_graph").joinpath("seed.json").read_text())


def statements(seed: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The parameterized writes that build the graph, in dependency order."""
    return [
        (EMPLOYEES, {"rows": seed["employees"]}),
        (PEOPLE, {"rows": seed["people"]}),
        (COMPANIES, {"rows": seed["companies"]}),
        (SANCTIONS, {"rows": seed["sanctions"]}),
        (ACCOUNTS, {"rows": seed["accounts"]}),
        (OWNERSHIP, {"rows": seed["ownership"]}),
        (DIRECTORS, {"rows": seed["directors"]}),
        (COVERAGE, {"rows": seed["coverage"]}),
        (IDENTITIES, {"rows": seed["identities"]}),
        (TRANSFERS, {"rows": seed["transfers"]}),
        (PAYMENTS, {"rows": seed["payments"]}),
        (CASES, {"rows": seed["cases"]}),
        (DEALS, {"rows": seed["deals"]}),
    ]


def cypher_literal(value: Any) -> str:
    """One value as a Cypher literal, for the printed script only. Writes use parameters."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        return f"'{escaped}'"
    if isinstance(value, list):
        return "[" + ", ".join(cypher_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"`{k}`: {cypher_literal(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"no Cypher literal for {type(value).__name__}")


def to_cypher_script(seed: dict[str, Any]) -> str:
    """The whole graph as a script you can paste into Neo4j Browser or the Aura query editor."""
    parts = [
        "// Bowser Capital's graph. Generated from neo4j/bank_graph/seed.json by `uv run seed --print`.",
        "// Paste it into Neo4j Browser or the Aura query editor; it is safe to run twice.",
    ]
    parts += [f"{c};" for c in CONSTRAINTS]
    for query, params in statements(seed):
        body = query.strip().replace("UNWIND $rows AS r", f"UNWIND {cypher_literal(params['rows'])} AS r", 1)
        parts.append(body + ";")
    return "\n\n".join(parts) + "\n"


def connect():
    """A driver for NEO4J_URI with NEO4J_USERNAME / NEO4J_PASSWORD, from the environment or `.env`."""
    from dotenv import find_dotenv, load_dotenv

    from neo4j import GraphDatabase

    load_dotenv(find_dotenv(usecwd=True))
    uri = os.environ.get("NEO4J_URI", "").strip()
    if not uri:
        sys.exit("NEO4J_URI is not set. Copy .env.example to .env and fill in the Neo4j block.")
    auth = (os.environ.get("NEO4J_USERNAME", "neo4j"), os.environ.get("NEO4J_PASSWORD", ""))
    return GraphDatabase.driver(uri, auth=auth)


def database() -> str:
    return os.environ.get("NEO4J_DATABASE", "").strip() or "neo4j"


def load(driver, seed: dict[str, Any], *, reset: bool = False) -> None:
    db = database()
    if reset:
        driver.execute_query(RESET, {"labels": LABELS}, database_=db)
    for constraint in CONSTRAINTS:
        driver.execute_query(constraint, database_=db)
    for query, params in statements(seed):
        driver.execute_query(query, params, database_=db)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="seed", description="Load Bowser Capital's graph into Neo4j.")
    parser.add_argument("--reset", action="store_true", help="delete the workshop's nodes first")
    parser.add_argument("--print", dest="print_only", action="store_true", help="print the graph as Cypher and exit")
    args = parser.parse_args(argv)
    seed = load_seed()
    if args.print_only:
        sys.stdout.write(to_cypher_script(seed))
        return
    with connect() as driver:
        driver.verify_connectivity()
        load(driver, seed, reset=args.reset)
    print(
        f"Loaded Bowser Capital: {len(seed['employees'])} employees, {len(seed['accounts'])} accounts, "
        f"{len(seed['payments'])} payments in review, {len(seed['cases'])} open case, {len(seed['deals'])} deals."
    )


def staff_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="staff", description="The employees the control plane governs.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    role = sub.add_parser("set-role")
    role.add_argument("email")
    role.add_argument("role")
    args = parser.parse_args(argv)

    with connect() as driver:
        db = database()
        if args.command == "set-role":
            records, _, _ = driver.execute_query(
                "MATCH (e:Employee {email: $email}) SET e.role = $role RETURN e.email AS email",
                {"email": args.email.lower(), "role": args.role},
                database_=db,
            )
            if not records:
                sys.exit(f"No employee {args.email}.")
        records, _, _ = driver.execute_query(
            "MATCH (e:Employee) RETURN e.email AS email, e.name AS name, e.role AS role, e.desk AS desk ORDER BY e.email",
            database_=db,
        )
    for r in records:
        print(f"{r['email']:<22} {r['name']:<12} {r['role']:<22} {r['desk']}")


if __name__ == "__main__":
    main()
