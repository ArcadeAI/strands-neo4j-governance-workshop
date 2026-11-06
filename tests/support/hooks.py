"""Calling the control plane's hooks over HTTP, the way Arcade does, for the tests."""

from __future__ import annotations

from typing import Any

TOKEN = "t0ken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TOOLS = {name: ["1.0.0"] for name in ("ListPaymentExceptions", "GetPayment", "ReleasePayment", "HoldPayment", "GetCase",
                                      "TraceFunds", "FreezeAccount", "FileSar", "ListDeals", "GetDeal", "RequestApproval", "Decide")}


def call(gate: Any, hook: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = gate.post(f"/hooks/{hook}", json=payload, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def access(gate: Any, user: str, tools: dict[str, list[str]] = TOOLS) -> list[str]:
    """The Bank tools hidden from `user`."""
    answer = call(gate, "access", {"user_id": user, "toolkits": {"Bank": {"tools": tools}}})
    return sorted(((answer.get("deny") or {}).get("Bank") or {}).get("tools") or {})


def pre(gate: Any, user: str, tool: str, inputs: dict[str, Any], toolkit: str = "Bank") -> dict[str, Any]:
    return call(gate, "pre", {"execution_id": "e1", "tool": {"toolkit": toolkit, "name": tool, "version": "1.0.0"},
                              "context": {"user_id": user}, "inputs": inputs})


def post(gate: Any, user: str, tool: str, output: Any, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    return call(gate, "post", {"execution_id": "e1", "tool": {"toolkit": "Bank", "name": tool, "version": "1.0.0"},
                               "context": {"user_id": user}, "inputs": inputs or {}, "output": output})


def request(graph: Any, **fields: Any) -> None:
    """An approval request in the graph, as `Bank.RequestApproval` would have written it."""
    row = {"request_id": "APR-1", "action": "release_payment", "resource_id": "PMT-5001", "case_id": None,
           "status": "pending", "requested_by": "pat@bank.example", "routed_to": "sana@bank.example",
           "decided_by": None, "decided_at": None, "consumed_at": None, "expires_at": None, "created_at": "2026-11-05T00:00:00Z"}
    graph.requests[fields.get("request_id", "APR-1")] = {**row, **fields}
