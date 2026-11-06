from __future__ import annotations

import os

import pytest

from support.fake_arcade import FakeArcadeEngine
from support.memory_graph import MemoryGraph

CREDENTIALS = (
    "ARCADE_API_KEY", "ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_PROFILE", "NEO4J_URI", "NEO4J_PASSWORD", "GATE_TOKEN", "MODEL_PROVIDER", "MODEL_ID", "LOAN_DESK_USER",
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


def live_neo4j() -> str:
    return os.environ.get("NEO4J_TEST_URI", "")
