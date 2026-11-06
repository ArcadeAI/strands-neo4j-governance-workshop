"""The Cypher, against a real Neo4j: skipped unless NEO4J_TEST_URI points at a database you can wipe.

    NEO4J_TEST_URI=bolt://localhost:7687 NEO4J_TEST_PASSWORD=... uv run pytest tests/test_neo4j_live.py

It reloads the seed with --reset semantics, so never point it at a database you care about.
The in-memory graph the rest of the suite uses is held to the same answers here.
"""

import asyncio
import os

import pytest

from loan_graph import load_seed
from loan_graph.seed import load
from support.memory_graph import MemoryGraph

URI = os.environ.get("NEO4J_TEST_URI", "")
pytestmark = pytest.mark.skipif(not URI, reason="set NEO4J_TEST_URI to run against a live Neo4j")


@pytest.fixture(scope="module")
def auth():
    return (os.environ.get("NEO4J_TEST_USERNAME", "neo4j"), os.environ.get("NEO4J_TEST_PASSWORD", ""))


@pytest.fixture
def directory(auth):
    from neo4j import GraphDatabase

    from loan_gate.directory import Neo4jDirectory

    driver = GraphDatabase.driver(URI, auth=auth)
    load(driver, load_seed(), reset=True)
    yield Neo4jDirectory(driver)
    driver.close()


def test_group_exposure_matches_the_memory_graph(directory):
    for loan in ("LN-2297", "LN-2291", "LN-2299"):
        assert directory.group_exposure(loan) == MemoryGraph().group_exposure(loan)
    assert directory.officer("alice@bank.example")["clearance"] == 50000
    assert directory.ping()


def test_the_tool_queries_match_the_memory_graph(directory, auth):
    from neo4j import AsyncGraphDatabase

    from loan_desk.graph import Neo4jLoanBook

    async def compare():
        driver = AsyncGraphDatabase.driver(URI, auth=auth)
        try:
            live, memory = Neo4jLoanBook(driver), MemoryGraph().book()
            assert await live.search_loans("pending", None, None) == await memory.search_loans("pending", None, None)
            assert sorted(map(str, await live.borrower_network("LN-2297"))) == sorted(map(str, await memory.borrower_network("LN-2297")))
            got, want = await live.get_loan("LN-2288"), await memory.get_loan("LN-2288")
            assert {k: v for k, v in got.items() if k != "guarantors"} == {k: v for k, v in want.items() if k != "guarantors"}
            assert await live.approvers_for(88000, "alice@bank.example") == await memory.approvers_for(88000, "alice@bank.example")
        finally:
            await driver.close()

    asyncio.run(compare())


class LiveGraph:
    """Both sides on one live database: the gate's directory and, per call, the tools' loan book."""

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

            from loan_desk.graph import Neo4jLoanBook

            async with AsyncGraphDatabase.driver(URI, auth=self.auth) as driver:
                return await getattr(Neo4jLoanBook(driver), name)(*args, **kwargs)

        return call


def test_the_governed_loop_on_neo4j(directory, auth):
    import json

    from loan_agent.agent import build_agent
    from loan_agent.cli import approvals
    from loan_agent.config import Settings
    from loan_agent.scripted import Call, ScriptedModel, steps
    from support.fake_arcade import FakeArcadeEngine

    engine = FakeArcadeEngine(LiveGraph(directory, auth))
    try:
        alice, charlie = Settings(user="alice@bank.example"), Settings(user="charlie@bank.example")
        approve = Call("LoanDesk_ApproveLoan", {"loan_id": "LN-2291", "amount": 95000})
        escalate = Call("LoanDesk_RequestApproval", {"action": "approve_loan", "resource_id": "LN-2291", "amount": 95000, "justification": "ok"})
        desk = build_agent(alice, model=ScriptedModel(steps(approve, escalate)), engine=engine)
        desk("go")
        refused, requested = desk.transcript.calls
        assert refused.refused
        request_id = json.loads(requested.text)["request_id"]
        assert approvals(engine, charlie, request_id, "approve", "fine")["status"] == "approved"

        retry = build_agent(alice, model=ScriptedModel(steps(approve)), engine=engine)
        retry("go")
        assert not retry.transcript.calls[0].refused
        assert json.loads(retry.transcript.calls[0].text)["status"] == "approved"
        assert directory.request(request_id)["consumed_at"]
        assert directory.group_exposure("LN-2297") == 47500 + 95000
    finally:
        engine.close()
