"""The Cypher, against a real Neo4j: skipped unless NEO4J_TEST_URI points at a database you can wipe.

    NEO4J_TEST_URI=bolt://localhost:7687 NEO4J_TEST_PASSWORD=... uv run pytest tests/test_neo4j_live.py

It reloads the seed with --reset semantics, so never point it at a database you care about.
The in-memory graph the rest of the suite uses is held to the same answers here.
"""

import asyncio
import json
import os

import pytest

from bank_graph import load_seed
from bank_graph.seed import load
from support.memory_graph import MemoryGraph

URI = os.environ.get("NEO4J_TEST_URI", "")
pytestmark = pytest.mark.skipif(not URI, reason="set NEO4J_TEST_URI to run against a live Neo4j")
AT = "2026-11-06T12:00:00Z"


@pytest.fixture(scope="module")
def auth():
    return (os.environ.get("NEO4J_TEST_USERNAME", "neo4j"), os.environ.get("NEO4J_TEST_PASSWORD", ""))


@pytest.fixture
def directory(auth):
    from neo4j import GraphDatabase

    from bank_gate.directory import Neo4jDirectory

    driver = GraphDatabase.driver(URI, auth=auth)
    load(driver, load_seed(), reset=True)
    yield Neo4jDirectory(driver)
    driver.close()


def test_the_gate_queries_match_the_memory_graph(directory):
    memory = MemoryGraph()
    for payment in ("PMT-5001", "PMT-5002", "PMT-5003"):
        assert directory.sanctions_proximity(payment, 3) == memory.sanctions_proximity(payment, 3)
        assert directory.inbound_near_threshold(payment, 8000, 10000, 14) == memory.inbound_near_threshold(payment, 8000, 10000, 14)
    for recipient in ("rita@bank.example", "omar@bank.example", "pat@bank.example", "rita.patel", "nobody@example.com"):
        assert directory.case_subject_near(recipient, 2) == memory.case_subject_near(recipient, 2)
    for email in ("ava@bank.example", "marco@bank.example", "dana@bank.example"):
        assert directory.linked(email, "P-HALE", 3) == memory.linked(email, "P-HALE", 3)
    for email in ("ian@bank.example", "mia@bank.example"):
        assert directory.deals_open_to(email, AT) == memory.deals_open_to(email, AT)
    assert directory.case("CASE-7001") == memory.case("CASE-7001")
    assert directory.employee("sana@bank.example") == memory.employee("sana@bank.example")
    assert directory.ping()


def test_the_tool_queries_match_the_memory_graph(directory, auth):
    from neo4j import AsyncGraphDatabase

    from bank_tools.graph import Neo4jBook

    def paths(chains):
        return sorted(json.dumps(chain, sort_keys=True) for chain in chains)

    async def compare():
        driver = AsyncGraphDatabase.driver(URI, auth=auth)
        try:
            live, memory = Neo4jBook(driver), MemoryGraph().book()
            assert await live.payment_exceptions() == await memory.payment_exceptions()
            assert await live.get_payment("PMT-5001") == await memory.get_payment("PMT-5001")
            assert await live.screen_party("Brightwater Trading") == await memory.screen_party("Brightwater Trading")
            assert await live.get_case("CASE-7001") == await memory.get_case("CASE-7001")
            assert paths(await live.trace_funds("ACC-HALE", 4)) == paths(await memory.trace_funds("ACC-HALE", 4))
            assert await live.trace_ownership("P-HALE") == await memory.trace_ownership("P-HALE")
            assert await live.company_profile("C-NORTHWIND") == await memory.company_profile("C-NORTHWIND")
            assert await live.list_deals() == await memory.list_deals()
            assert await live.approvers(["sanctions_officer"]) == await memory.approvers(["sanctions_officer"])
        finally:
            await driver.close()

    asyncio.run(compare())


class LiveGraph:
    """Both sides on one live database: the gate's directory and, per call, the tools' book."""

    def __init__(self, directory, auth):
        self.directory, self.auth = directory, auth

    def __getattr__(self, name):
        return getattr(self.directory, name)

    def book(self):
        return LiveBook(self.auth)


class LiveBook:
    def __init__(self, auth):
        self.auth = auth

    def __getattr__(self, name):
        async def call(*args, **kwargs):
            from neo4j import AsyncGraphDatabase

            from bank_tools.graph import Neo4jBook

            async with AsyncGraphDatabase.driver(URI, auth=self.auth) as driver:
                return await getattr(Neo4jBook(driver), name)(*args, **kwargs)

        return call


def test_the_payments_hold_on_neo4j(directory, auth):
    from bank_agent.cli import approvals
    from bank_agent.config import Settings
    from bank_agent.desks.payments import build_payments_desk
    from support.fake_arcade import FakeArcadeEngine

    engine = FakeArcadeEngine(LiveGraph(directory, auth))
    try:
        pat, sana = Settings(user="pat@bank.example", desk="payments"), Settings(user="sana@bank.example", desk="payments")
        run = build_payments_desk(pat, engine=engine)
        run("Work PMT-5001")
        refused = next(c for c in run.transcript.calls if c.name == "Bank_ReleasePayment")
        assert refused.refused and "Orlov Maritime Ltd" in refused.text
        requested = next(c for c in run.transcript.calls if c.name == "Bank_RequestApproval")
        request_id = json.loads(requested.text)["request_id"]
        assert directory.request(request_id)["routed_to"] == "sana@bank.example"
        assert approvals(engine, sana, request_id, "approve", "Originator confirmed.")["status"] == "approved"

        retry = build_payments_desk(pat, engine=engine)
        retry("Work PMT-5001")
        released = next(c for c in retry.transcript.calls if c.name == "Bank_ReleasePayment")
        assert not released.refused
        assert directory.request(request_id)["consumed_at"]
    finally:
        engine.close()
