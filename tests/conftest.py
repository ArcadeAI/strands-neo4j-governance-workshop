from __future__ import annotations

import os

import pytest

from support.fake_arcade import FakeArcadeEngine
from support.hooks import TOKEN
from support.memory_graph import MemoryGraph

CREDENTIALS = (
    "ARCADE_API_KEY", "ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_PROFILE", "NEO4J_URI", "NEO4J_PASSWORD", "GATE_TOKEN", "MODEL_PROVIDER", "MODEL_ID", "BANK_USER",
    "CONNECTED_APPS_USER",
)


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    """Nothing in the suite may reach a real service, whatever the shell or `.env` holds."""
    for key in CREDENTIALS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    yield


@pytest.fixture
def graph() -> MemoryGraph:
    return MemoryGraph()


@pytest.fixture
def arcade(graph):
    engine = FakeArcadeEngine(graph)
    yield engine
    engine.close()


@pytest.fixture
def audit():
    from bank_gate.audit import AuditLog

    return AuditLog(echo=False)


@pytest.fixture
def gate(graph, audit):
    """The control plane over HTTP, on the shipped policies and the in-memory graph."""
    from fastapi.testclient import TestClient

    from bank_gate.policy import load_policy
    from bank_gate.server import create_app

    return TestClient(create_app(load_policy(), graph, TOKEN, audit))


def live_neo4j() -> str:
    return os.environ.get("NEO4J_TEST_URI", "")
