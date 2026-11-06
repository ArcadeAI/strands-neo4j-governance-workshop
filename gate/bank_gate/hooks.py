"""The three hooks, as functions from Arcade's payload to Arcade's response.

The payloads and responses follow Arcade's Contextual Access webhook contract
(https://docs.arcade.dev/en/references/contextual-access-webhook-api): `code` is `OK` or
`CHECK_FAILED`, a refusal carries `error_message` for the agent, and an access response's
`deny` map reuses the request's own `toolkits` shape.

Every handler fails closed: a caller the graph does not know as an employee gets nothing from
the Bank toolkit, and a directory that cannot be read refuses the call rather than guessing.

Calls to other toolkits pass through, except the outbound tools a rule names (Gmail.SendEmail,
Slack.SendDmToUser). Those are checked on who receives the message, not who sends it: a tip-off
is a tip-off whoever's Gmail it leaves from.
"""

from __future__ import annotations

import json
from typing import Any

from bank_gate.audit import AuditLog
from bank_gate.directory import Directory, now
from bank_gate.policy import Facts, Policy, apply_post, decide_pre, hidden_tools

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

    def _facts(self, user: str, subject: dict[str, Any] | None, inputs: dict[str, Any], tool: str) -> Facts:
        return Facts(user=user, subject=subject or {}, inputs=inputs, directory=self.directory, tool=tool)

    def access(self, payload: dict[str, Any]) -> dict[str, Any]:
        user = user_of(payload)
        toolkits: dict[str, Any] = payload.get("toolkits") or {}
        subject = self.directory.employee(user) if user else None
        deny: dict[str, Any] = {}
        for toolkit, info in toolkits.items():
            if toolkit.lower() != self.policy.toolkit.lower():
                continue
            versions = (info or {}).get("tools") or {}
            if not versions:
                continue
            if subject is None:
                deny[toolkit] = {"tools": dict(versions)}
                self.audit.record(hook="access", outcome="hidden", user_id=user or "-", tool=f"{toolkit}.*",
                                  detail="not a Larkspur employee")
                continue
            hidden = hidden_tools(self.policy, self._facts(user, subject, {}, ""), list(versions))
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

        if not self.policy.governs(toolkit, tool):
            self.audit.record(**base, outcome="passed", detail="not a governed tool")
            return {"code": OK}

        internal = toolkit.lower() == self.policy.toolkit.lower()
        subject = self.directory.employee(user) if user else None
        if internal and subject is None:
            message = f"DENIED: {user or 'this caller'} is not a Larkspur employee, so no Bank tool runs for them. [ref {execution_id}]"
            self.audit.record(**base, outcome="denied", rule="baseline.employees-only", detail=message)
            return {"code": CHECK_FAILED, "error_message": message}

        name = tool if internal else f"{toolkit}.{tool}"
        decision = decide_pre(self.policy, name, self._facts(user, subject, inputs, name))
        if decision.allowed:
            self.audit.record(**base, outcome="allowed")
            return {"code": OK}

        rule = decision.rule
        if rule and rule.escalate and rule.resource:
            resource = str(inputs.get(rule.resource) or "")
            grant = self.directory.find_grant(user, rule.escalate, resource) if resource else None
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
        if toolkit.lower() != self.policy.toolkit.lower():
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

        subject = (self.directory.employee(user) if user else None) or {"email": user, "role": None}
        changed, applied = apply_post(self.policy, tool, self._facts(user, subject, payload.get("inputs") or {}, tool), output)
        if not applied:
            return {"code": OK}
        for rule, fields in applied:
            self.audit.record(hook="post", execution_id=execution_id, user_id=user or "-", tool=f"{toolkit}.{tool}",
                              outcome="redacted", rule=rule.id, detail=", ".join(fields))
        if was_text and not isinstance(changed, str):
            changed = json.dumps(changed)
        return {"code": OK, "override": {"output": changed}}
