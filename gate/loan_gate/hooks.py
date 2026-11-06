"""The three hooks, as functions from Arcade's payload to Arcade's response.

The payloads and responses follow Arcade's Contextual Access webhook contract
(https://docs.arcade.dev/en/references/contextual-access-webhook-api): `code` is `OK` or
`CHECK_FAILED`, a refusal carries `error_message` for the agent, and an access response's
`deny` map reuses the request's own `toolkits` shape.

Every handler fails closed: a caller the graph does not know gets nothing from the governed
toolkit, and a directory that cannot be read refuses the call rather than guessing. Calls to
other toolkits (Slack, Gmail) pass through untouched; this control plane governs the loan desk.
"""

from __future__ import annotations

import json
from typing import Any

from loan_gate.audit import AuditLog
from loan_gate.directory import Directory, now
from loan_gate.policy import Facts, Policy, apply_post, decide_pre, hidden_tools, number

OK = "OK"
CHECK_FAILED = "CHECK_FAILED"


def user_of(payload: dict[str, Any]) -> str:
    context = payload.get("context") or {}
    return str(context.get("user_id") or payload.get("user_id") or "").strip().lower()


def tool_of(payload: dict[str, Any]) -> tuple[str, str]:
    tool = payload.get("tool") or {}
    return str(tool.get("toolkit") or ""), str(tool.get("name") or "")


class Hooks:
    def __init__(self, policy: Policy, directory: Directory, audit: AuditLog) -> None:
        self.policy = policy
        self.directory = directory
        self.audit = audit

    def access(self, payload: dict[str, Any]) -> dict[str, Any]:
        user = user_of(payload)
        toolkits: dict[str, Any] = payload.get("toolkits") or {}
        subject = self.directory.officer(user) if user else None
        deny: dict[str, Any] = {}
        for toolkit, info in toolkits.items():
            if not self.policy.governs(toolkit):
                continue
            versions = (info or {}).get("tools") or {}
            if not versions:
                continue
            if subject is None:
                deny[toolkit] = {"tools": dict(versions)}
                self.audit.record(hook="access", outcome="hidden", user_id=user or "-", tool=f"{toolkit}.*",
                                  detail="not an officer on this loan desk")
                continue
            hidden = hidden_tools(self.policy, subject, list(versions))
            if hidden:
                deny[toolkit] = {"tools": {name: versions[name] for name in hidden}}
            for name in versions:
                rule = hidden.get(name)
                self.audit.record(hook="access", outcome="hidden" if rule else "allowed", user_id=user,
                                  tool=f"{toolkit}.{name}", rule=rule.id if rule else None)
        return {"deny": deny} if deny else {}

    def pre(self, payload: dict[str, Any]) -> dict[str, Any]:
        execution_id = str(payload.get("execution_id") or "")
        toolkit, tool = tool_of(payload)
        user = user_of(payload)
        inputs: dict[str, Any] = payload.get("inputs") or {}
        base = {"hook": "pre", "execution_id": execution_id, "user_id": user or "-", "tool": f"{toolkit}.{tool}"}

        if not self.policy.governs(toolkit):
            self.audit.record(**base, outcome="passed", detail="not a governed toolkit")
            return {"code": OK}

        subject = self.directory.officer(user) if user else None
        if subject is None:
            message = f"DENIED: {user or 'this caller'} is not an officer on this loan desk, so no loan desk tool runs for them. [ref {execution_id}]"
            self.audit.record(**base, outcome="denied", rule="baseline.registered-officers-only", detail=message)
            return {"code": CHECK_FAILED, "error_message": message}

        facts = Facts(
            user=user,
            subject=subject,
            inputs=inputs,
            request_lookup=self.directory.request,
            exposure_lookup=self.directory.group_exposure,
        )
        decision = decide_pre(self.policy, tool, facts)
        if decision.allowed:
            self.audit.record(**base, outcome="allowed")
            return {"code": OK}

        rule = decision.rule
        if rule and rule.escalate:
            amount = number(inputs.get("amount"))
            resource = str(inputs.get("loan_id") or inputs.get("resource_id") or "")
            grant = self.directory.find_grant(user, rule.escalate, resource, amount) if amount is not None else None
            if grant and self.directory.consume_grant(grant["request_id"], now()):
                self.audit.record(**base, outcome="granted", rule=rule.id,
                                  detail=f"single-use approval {grant['request_id']} from {grant.get('decided_by')}")
                return {"code": OK}

        message = f"{decision.message} [ref {execution_id}]"
        self.audit.record(**base, outcome="denied", rule=rule.id if rule else None, detail=decision.message)
        return {"code": CHECK_FAILED, "error_message": message}

    def post(self, payload: dict[str, Any]) -> dict[str, Any]:
        execution_id = str(payload.get("execution_id") or "")
        toolkit, tool = tool_of(payload)
        user = user_of(payload)
        if not self.policy.governs(toolkit):
            return {"code": OK}
        if "output" not in payload or payload.get("output") is None:
            return {"code": OK}

        output = payload["output"]
        was_text = isinstance(output, str)
        if was_text:
            try:
                output = json.loads(output)
            except ValueError:
                pass

        subject = (self.directory.officer(user) if user else None) or {"email": user, "role": None, "clearance": 0}
        changed, applied = apply_post(self.policy, tool, subject, output)
        if not applied:
            return {"code": OK}
        for rule, fields in applied:
            self.audit.record(hook="post", execution_id=execution_id, user_id=user or "-", tool=f"{toolkit}.{tool}",
                              outcome="redacted", rule=rule.id, detail=", ".join(fields))
        if was_text and not isinstance(changed, str):
            changed = json.dumps(changed)
        return {"code": OK, "override": {"output": changed}}
