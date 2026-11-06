"""The policy: rules loaded from `gate/policies/*.json`, and the decisions they make.

Nothing here talks to Arcade or Neo4j directly. Each function takes the facts it needs (who is
calling, which tool, with what inputs) and a `Directory` that answers graph questions (how many
hops from a listed entity, how many payments just under the threshold, who is near a case's
subject), and returns a decision. The whole policy is testable against an in-memory graph.

The condition vocabulary is closed on purpose: a policy file can only say things this module
knows how to check, and anything else is refused when the file loads.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bank_gate.directory import Directory

HOOKS = ("access", "pre", "post")
TOOLKIT = "Bank"

CONDITIONS: dict[str, type | tuple[type, ...]] = {
    "role_in": list,
    "role_not_in": list,
    "always": bool,
    "beneficiary_near_sanctioned": int,
    "structuring": dict,
    "recipient_near_case_subject": int,
    "request_not_pending": bool,
    "caller_is_requester": bool,
    "request_action_in": list,
    "caller_owns_case": bool,
    "caller_linked_to_subject": int,
    "not_over_wall": bool,
}

STRUCTURING_KEYS = {"floor", "threshold", "window_days", "min_count"}

BANK_TOOLS = frozenset({
    "ListPaymentExceptions", "GetPayment", "ScreenParty", "ReleasePayment", "HoldPayment",
    "GetCase", "TraceFunds", "TraceOwnership", "FreezeAccount", "FileSar",
    "SearchCompanies", "GetCompanyProfile", "ListDeals", "GetDeal",
    "RequestApproval", "ListApprovals", "Decide",
})

# Tools outside the Bank toolkit a rule may govern, and the input that names who receives the message.
OUTBOUND: dict[str, str] = {
    "Gmail.SendEmail": "recipient",
    "Slack.SendDmToUser": "user_name",
}

DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "policies"


class PolicyError(ValueError):
    """The policy file says something this module cannot enforce."""


@dataclass(frozen=True)
class Rule:
    id: str
    hook: str
    tools: tuple[str, ...]
    when: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    description: str = ""
    escalate: str | None = None
    resource: str | None = None
    redact: tuple[str, ...] = ()
    replacement: str = "[REDACTED]"
    neutralize: tuple[str, ...] = ()
    per_record: str | None = None

    def covers(self, tool: str) -> bool:
        return tool in self.tools or ("*" in self.tools and tool in BANK_TOOLS)


@dataclass(frozen=True)
class Policy:
    rules: tuple[Rule, ...]
    toolkit: str = TOOLKIT

    def governs(self, toolkit: str, tool: str = "") -> bool:
        if toolkit.lower() == self.toolkit.lower():
            return True
        return any(f"{toolkit}.{tool}" in r.tools for r in self.rules)

    def for_hook(self, hook: str, tool: str) -> list[Rule]:
        return [r for r in self.rules if r.hook == hook and r.covers(tool)]


def _check_when(rid: str, when: Mapping[str, Any]) -> None:
    for key, value in when.items():
        if key not in CONDITIONS:
            raise PolicyError(f"{rid}: unknown condition {key!r}; known: {', '.join(sorted(CONDITIONS))}")
        expected = CONDITIONS[key]
        if isinstance(value, bool) and expected is int or not isinstance(value, expected):
            raise PolicyError(f"{rid}: condition {key!r} has the wrong type")
        if key == "structuring" and set(value) != STRUCTURING_KEYS:
            raise PolicyError(f"{rid}: structuring takes exactly {', '.join(sorted(STRUCTURING_KEYS))}")


def parse_rules(raw: Mapping[str, Any], seen: set[str] | None = None) -> list[Rule]:
    """The rules of one policy file, checked against the vocabulary."""
    seen = set() if seen is None else seen
    toolkit = raw.get("toolkit")
    if toolkit != TOOLKIT:
        raise PolicyError(f"policy: `toolkit` must be {TOOLKIT}, the toolkit the Bank MCP server deploys as")
    rules: list[Rule] = []
    for entry in raw.get("rules", []):
        rid = entry.get("id")
        if not isinstance(rid, str) or not rid:
            raise PolicyError("policy: every rule needs an `id`")
        if rid in seen:
            raise PolicyError(f"{rid}: duplicate rule id")
        seen.add(rid)
        hook = entry.get("hook")
        if hook not in HOOKS:
            raise PolicyError(f"{rid}: `hook` must be one of {', '.join(HOOKS)}")
        tools = entry.get("tools")
        if not isinstance(tools, list) or not tools:
            raise PolicyError(f"{rid}: `tools` must list tool names, or ['*']")
        unknown = sorted(t for t in tools if t != "*" and t not in BANK_TOOLS and t not in OUTBOUND)
        if unknown:
            raise PolicyError(f"{rid}: no such tool {', '.join(unknown)} (Bank tools are PascalCase, as in hook payloads; "
                              f"others are named in full, such as Gmail.SendEmail)")
        if hook != "pre" and any(t in OUTBOUND for t in tools):
            raise PolicyError(f"{rid}: tools outside the Bank toolkit are governed in the pre hook only")
        when = entry.get("when", {})
        _check_when(rid, when)
        redact = tuple(entry.get("redact", ()))
        neutralize = tuple(entry.get("neutralize", ()))
        if hook == "post" and not (redact or neutralize):
            raise PolicyError(f"{rid}: a post rule must `redact` or `neutralize` fields")
        if hook != "post" and (redact or neutralize or entry.get("per_record")):
            raise PolicyError(f"{rid}: only post rules change output")
        if hook in ("access", "pre") and not entry.get("reason"):
            raise PolicyError(f"{rid}: a denying rule needs a `reason`")
        if entry.get("escalate") and not entry.get("resource"):
            raise PolicyError(f"{rid}: a rule that can be escalated names the input that is its `resource`")
        rules.append(
            Rule(
                id=rid, hook=hook, tools=tuple(tools), when=dict(when), reason=entry.get("reason", ""),
                description=entry.get("description", ""), escalate=entry.get("escalate"), resource=entry.get("resource"),
                redact=redact, replacement=entry.get("replacement", "[REDACTED]"), neutralize=neutralize,
                per_record=entry.get("per_record"),
            )
        )
    return rules


def parse_policy(raw: Mapping[str, Any]) -> Policy:
    return Policy(rules=tuple(parse_rules(raw)))


def load_policy(path: Path | str = DEFAULT_POLICY) -> Policy:
    """One policy file, or every `*.json` in a directory, in file-name order."""
    path = Path(path)
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not files:
        raise PolicyError(f"no policy files in {path}")
    seen: set[str] = set()
    rules: list[Rule] = []
    for file in files:
        try:
            rules += parse_rules(json.loads(file.read_text()), seen)
        except PolicyError as exc:
            raise PolicyError(f"{file.name}: {exc}") from exc
    return Policy(rules=tuple(rules))


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def show(value: Any) -> str:
    """A value as the reason text shows it: 9750, not 9750.0; a chain as a - b - c."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return " - ".join(map(str, value))
    return str(value)


def render(template: str, facts: Mapping[str, Any]) -> str:
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: show(facts.get(m.group(1), m.group(0))), template)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Facts:
    """What a rule can look at. Graph questions go to `directory` only when a rule asks them."""

    user: str
    subject: Mapping[str, Any]
    inputs: Mapping[str, Any]
    directory: Directory
    tool: str = ""
    record: Mapping[str, Any] | None = None
    at: str = field(default_factory=utc_now)
    _request: Any = None
    _request_read: bool = False
    _open_deals: Any = None

    @property
    def role(self) -> str | None:
        return self.subject.get("role")

    @property
    def request(self) -> Mapping[str, Any] | None:
        if not self._request_read:
            request_id = self.inputs.get("request_id")
            self._request = self.directory.request(str(request_id)) if request_id else None
            self._request_read = True
        return self._request

    def open_deals(self) -> set[str]:
        if self._open_deals is None:
            self._open_deals = set(self.directory.deals_open_to(self.user, self.at)) if self.user else set()
        return self._open_deals

    def case_of_request(self) -> Mapping[str, Any] | None:
        request = self.request
        case_id = (request or {}).get("case_id") or self.inputs.get("case_id")
        return self.directory.case(str(case_id)) if case_id else None

    def template_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {**self.inputs, "user": self.user, "role": self.role}
        if self._request_read and self.request:
            values |= {"request_action": self.request.get("action"), "requested_by": self.request.get("requested_by"),
                       "routed_to": self.request.get("routed_to"), "resource_id": self.request.get("resource_id")}
        return values


def holds(rule: Rule, facts: Facts, extra: dict[str, Any]) -> bool:
    """Whether every condition of `rule` is true for these facts. `extra` collects values for the reason text."""
    for key, expected in rule.when.items():
        if key == "role_in":
            ok = facts.role in expected
        elif key == "role_not_in":
            ok = facts.role not in expected
        elif key == "always":
            ok = expected
        elif key == "beneficiary_near_sanctioned":
            payment_id = facts.inputs.get("payment_id")
            hit = facts.directory.sanctions_proximity(str(payment_id), expected) if payment_id else None
            if hit:
                extra.update(hit)
            ok = hit is not None
        elif key == "structuring":
            payment_id = facts.inputs.get("payment_id")
            found = facts.directory.inbound_near_threshold(
                str(payment_id), expected["floor"], expected["threshold"], expected["window_days"]
            ) if payment_id else None
            if found is None:
                ok = False
            else:
                count = found["count"] + (1 if expected["floor"] <= found["amount"] < expected["threshold"] else 0)
                extra.update(found, count=count, **{k: expected[k] for k in ("floor", "threshold", "window_days")})
                ok = count >= expected["min_count"]
        elif key == "recipient_near_case_subject":
            recipient = str(facts.inputs.get(OUTBOUND.get(facts.tool, ""), "") or "").strip().lower()
            hit = facts.directory.case_subject_near(recipient, expected) if recipient else None
            if hit:
                extra.update(hit, recipient=recipient)
            ok = hit is not None
        elif key == "request_not_pending":
            request = facts.request
            ok = (request is None or request.get("status") != "pending") == expected
        elif key == "caller_is_requester":
            request = facts.request
            ok = request is not None and (str(request.get("requested_by", "")).lower() == facts.user) == expected
        elif key == "request_action_in":
            request = facts.request
            ok = request is not None and request.get("action") in expected
        elif key == "caller_owns_case":
            case = facts.case_of_request()
            if case:
                extra.update(case_id=case["case_id"], subject=case["subject"])
            ok = case is not None and (case.get("owner") == facts.user) == expected
        elif key == "caller_linked_to_subject":
            case = facts.case_of_request()
            link = facts.directory.linked(facts.user, case["subject_id"], expected) if case else None
            if link:
                extra.update(link, case_id=case["case_id"], subject=case["subject"])
            ok = link is not None
        elif key == "not_over_wall":
            deal_id = (facts.record or facts.inputs).get("deal_id")
            open_deals = facts.open_deals()
            ok = (str(deal_id) not in open_deals if deal_id else not open_deals) == expected
        else:
            raise PolicyError(f"{rule.id}: unknown condition {key!r}")
        if not ok:
            return False
    return True


@dataclass(frozen=True)
class PreDecision:
    allowed: bool
    rule: Rule | None = None
    message: str = ""


def decide_pre(policy: Policy, tool: str, facts: Facts) -> PreDecision:
    """The first pre rule that holds for this call, or an allow."""
    for rule in policy.for_hook("pre", tool):
        extra: dict[str, Any] = {}
        if holds(rule, facts, extra):
            return PreDecision(False, rule, render(rule.reason, facts.template_values() | extra))
    return PreDecision(True)


def hidden_tools(policy: Policy, facts: Facts, tools: list[str]) -> dict[str, Rule]:
    """The tools an access rule hides from this caller, with the rule that hides each."""
    hidden: dict[str, Rule] = {}
    for tool in tools:
        for rule in policy.for_hook("access", tool):
            if holds(rule, facts, {}):
                hidden[tool] = rule
                break
    return hidden


INSTRUCTION_MARKERS = re.compile(
    r"(system note|note for automated review|ignore (all |any )?(earlier|previous|prior) (screening )?instructions?|"
    r"do not mention this|you are an? (ai|assistant|model)|automated review)",
    re.IGNORECASE,
)
REMOVED = "[removed by policy: text addressed to an AI system]"


def neutralize_text(text: str) -> str:
    """Drop every paragraph that reads as an instruction to a model, keeping the rest of the text.

    A keyword heuristic, enough to show where the control sits. A production control plane would
    put a classifier here; the hook point is the same.
    """
    paragraphs = re.split(r"\n\s*\n", text)
    kept = [p for p in paragraphs if not INSTRUCTION_MARKERS.search(p)]
    if len(kept) == len(paragraphs):
        return text
    return "\n\n".join([*kept, REMOVED])


def apply_post(policy: Policy, tool: str, facts: Facts, output: Any) -> tuple[Any, list[tuple[Rule, list[str]]]]:
    """The output with every post rule that holds applied, and which fields each rule changed.

    A rule with `per_record` is checked once per object in the output that carries that key (each
    deal record, wherever it appears), so one rule masks some records and leaves others.
    """
    applied: list[tuple[Rule, list[str]]] = []
    for rule in policy.for_hook("post", tool):
        if rule.per_record is None and not holds(rule, facts, {}):
            continue
        changed: list[str] = []

        def walk(node: Any, path: str = "", active: bool = rule.per_record is None, rule: Rule = rule, changed: list[str] = changed) -> Any:
            if isinstance(node, dict):
                here_active = active
                if rule.per_record is not None and rule.per_record in node:
                    facts.record = node
                    here_active = holds(rule, facts, {})
                    facts.record = None
                out = {}
                for key, value in node.items():
                    here = f"{path}.{key}" if path else key
                    if here_active and key in rule.redact and value is not None and value != rule.replacement:
                        out[key] = rule.replacement
                        changed.append(here)
                    elif key in rule.neutralize and isinstance(value, str):
                        cleaned = neutralize_text(value)
                        if cleaned != value:
                            changed.append(here)
                        out[key] = cleaned
                    else:
                        out[key] = walk(value, here, here_active and rule.per_record is None)
                return out
            if isinstance(node, list):
                return [walk(item, f"{path}[{i}]", active) for i, item in enumerate(node)]
            return node

        output = walk(output)
        if changed:
            applied.append((rule, changed))
    return output, applied
