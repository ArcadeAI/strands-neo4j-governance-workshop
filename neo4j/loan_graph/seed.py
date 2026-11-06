"""Load the loan desk graph into Neo4j, print it as Cypher, and manage the officers in it.

    uv run seed              # load seed.json into the database NEO4J_URI names
    uv run seed --reset      # delete the workshop's nodes first, then load
    uv run seed --print      # print the same graph as one Cypher script (neo4j/seed.cypher)

    uv run officers list
    uv run officers set-clearance alice@bank.example 250000
    uv run officers set-role bob@bank.example loan_officer

The officers are the people the control plane governs: their role and clearance live in the
graph, next to the loans, and the gate reads them on every call. Changing a clearance here
changes what the policy allows on the next tool call, with no restart.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from importlib import resources
from typing import Any

LABELS = ["Officer", "Person", "Company", "Loan", "Decision", "ApprovalRequest"]

CONSTRAINTS = [
    "CREATE CONSTRAINT officer_email IF NOT EXISTS FOR (o:Officer) REQUIRE o.email IS UNIQUE",
    "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT company_id IF NOT EXISTS FOR (c:Company) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT loan_id IF NOT EXISTS FOR (l:Loan) REQUIRE l.id IS UNIQUE",
    "CREATE CONSTRAINT decision_id IF NOT EXISTS FOR (d:Decision) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT approval_id IF NOT EXISTS FOR (r:ApprovalRequest) REQUIRE r.id IS UNIQUE",
]

RESET = "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) DETACH DELETE n"

OFFICERS = """
UNWIND $rows AS r
MERGE (o:Officer {email: r.email})
SET o.name = r.name, o.role = r.role, o.clearance = r.clearance
"""

PEOPLE = """
UNWIND $rows AS r
MERGE (p:Person {id: r.id})
SET p.name = r.name
"""

COMPANIES = """
UNWIND $rows AS r
MERGE (c:Company {id: r.id})
SET c.name = r.name, c.contact_email = r.contact_email, c.annual_revenue = r.annual_revenue,
    c.years_in_business = r.years_in_business, c.bank_account_number = r.bank_account_number,
    c.tax_id = r.tax_id
"""

OWNERSHIP = """
UNWIND $rows AS r
MATCH (p:Person {id: r.person}), (c:Company {id: r.company})
MERGE (p)-[o:OWNS]->(c)
SET o.pct = r.pct
"""

LOANS = """
UNWIND $rows AS r
MATCH (c:Company {id: r.company})
MERGE (l:Loan {id: r.loan_id})
SET l.amount = r.amount, l.status = r.status, l.purpose = r.purpose,
    l.submitted_at = r.submitted_at, l.credit_score = r.credit_score,
    l.underwriter_notes = r.underwriter_notes
MERGE (c)-[:APPLIED_FOR]->(l)
"""

GUARANTEES = """
UNWIND $rows AS r
MATCH (p:Person {id: r.person}), (l:Loan {id: r.loan_id})
MERGE (p)-[:GUARANTEES]->(l)
"""

DECISIONS = """
UNWIND $rows AS r
MATCH (l:Loan {id: r.loan_id})
MERGE (d:Decision {id: r.id})
SET d.kind = r.decision, d.amount = r.amount, d.reason = r.reason,
    d.decided_at = r.decided_at, d.decided_by = r.decided_by
MERGE (d)-[:ON]->(l)
WITH d, r
MATCH (o:Officer {email: r.decided_by})
MERGE (o)-[:MADE]->(d)
"""


def load_seed() -> dict[str, Any]:
    """The graph as `seed.json` holds it."""
    return json.loads(resources.files("loan_graph").joinpath("seed.json").read_text())


def statements(seed: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The parameterized writes that build the graph, in dependency order."""
    loans = seed["loans"]
    return [
        (OFFICERS, {"rows": seed["officers"]}),
        (PEOPLE, {"rows": seed["people"]}),
        (COMPANIES, {"rows": seed["companies"]}),
        (OWNERSHIP, {"rows": seed["ownership"]}),
        (LOANS, {"rows": [{k: v for k, v in loan.items() if k not in ("guarantors", "decisions")} for loan in loans]}),
        (GUARANTEES, {"rows": [{"person": p, "loan_id": loan["loan_id"]} for loan in loans for p in loan["guarantors"]]}),
        (DECISIONS, {"rows": [{**d, "loan_id": loan["loan_id"]} for loan in loans for d in loan["decisions"]]}),
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
        "// The loan desk graph. Generated from neo4j/loan_graph/seed.json by `uv run seed --print`.",
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
    parser = argparse.ArgumentParser(prog="seed", description="Load the loan desk graph into Neo4j.")
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
        records, _, _ = driver.execute_query(
            "MATCH (l:Loan) RETURN l.status AS status, count(*) AS n ORDER BY status", database_=database()
        )
    summary = ", ".join(f"{r['n']} {r['status']}" for r in records)
    print(f"Loaded the loan desk graph: {len(seed['loans'])} loans ({summary}), {len(seed['officers'])} officers.")


def officers_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="officers", description="The officers the control plane governs.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    clearance = sub.add_parser("set-clearance")
    clearance.add_argument("email")
    clearance.add_argument("clearance", type=float)
    role = sub.add_parser("set-role")
    role.add_argument("email")
    role.add_argument("role")
    args = parser.parse_args(argv)

    with connect() as driver:
        db = database()
        if args.command == "set-clearance":
            records, _, _ = driver.execute_query(
                "MATCH (o:Officer {email: $email}) SET o.clearance = $clearance RETURN o.email AS email",
                {"email": args.email.lower(), "clearance": args.clearance},
                database_=db,
            )
            if not records:
                sys.exit(f"No officer {args.email}.")
        elif args.command == "set-role":
            records, _, _ = driver.execute_query(
                "MATCH (o:Officer {email: $email}) SET o.role = $role RETURN o.email AS email",
                {"email": args.email.lower(), "role": args.role},
                database_=db,
            )
            if not records:
                sys.exit(f"No officer {args.email}.")
        records, _, _ = driver.execute_query(
            "MATCH (o:Officer) RETURN o.email AS email, o.name AS name, o.role AS role, o.clearance AS clearance "
            "ORDER BY o.clearance",
            database_=db,
        )
    for r in records:
        print(f"{r['email']:<28} {r['name']:<10} {r['role']:<22} {r['clearance']:>12,.0f}")


if __name__ == "__main__":
    main()
