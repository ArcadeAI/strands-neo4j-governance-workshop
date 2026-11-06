"""The policy: rules loaded from `gate/policy.json`, and the decisions they make.

Nothing here talks to Arcade or Neo4j. Each function takes the facts it needs (who is
calling, which tool, with what inputs, and what the graph says) and returns a decision, so the
whole policy is testable without a network.

The condition vocabulary is closed on purpose: a policy file can only say things this module
knows how to check, and anything else is refused when the file loads.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HOOKS = ("access", "pre", "post")

CONDITIONS: dict[str, type | tuple[type, ...]] = {
    "role_in": list,
    "input_exceeds_clearance": str,
    "group_exposure_exceeds_clearance": str,
    "clearance_below": (int, float),
    "caller_is_requester": bool,
    "request_exceeds_clearance": bool,
    "request_not_pending": bool,
}

KNOWN_TOOLS = frozenset(
    {"SearchLoans", "GetLoan", "GetBorrowerNetwork", "ApproveLoan", "DenyLoan", "RequestApproval", "ListApprovals", "Decide"}
)

DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "policy.json"


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
    redact: tuple[str, ...] = ()
    replacement: str = "[REDACTED]"
    neutralize: tuple[str, ...] = ()

    def covers(self, tool: str) -> bool:
        return "*" in self.tools or tool in self.tools


@dataclass(frozen=True)
class Policy:
    toolkit: str
    rules: tuple[Rule, ...]

    def governs(self, toolkit: str) -> bool:
        return toolkit.lower() == self.toolkit.lower()

    def for_hook(self, hook: str, tool: str) -> list[Rule]:
        return [r for r in self.rules if r.hook == hook and r.covers(tool)]


def parse_policy(raw: Mapping[str, Any]) -> Policy:
    toolkit = raw.get("toolkit")
    if not isinstance(toolkit, str) or not toolkit:
        raise PolicyError("policy: `toolkit` must name the governed toolkit, for example LoanDesk")
    rules: list[Rule] = []
    seen: set[str] = set()
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
        unknown = sorted(t for t in tools if t != "*" and t not in KNOWN_TOOLS)
        if unknown:
            raise PolicyError(f"{rid}: no such LoanDesk tool {', '.join(unknown)} (names are PascalCase, as in hook payloads)")
        when = entry.get("when", {})
        for key, value in when.items():
            if key not in CONDITIONS:
                raise PolicyError(f"{rid}: unknown condition {key!r}; known: {', '.join(sorted(CONDITIONS))}")
            if not isinstance(value, CONDITIONS[key]):
                raise PolicyError(f"{rid}: condition {key!r} has the wrong type")
        redact = tuple(entry.get("redact", ()))
        neutralize = tuple(entry.get("neutralize", ()))
        if hook == "post" and not (redact or neutralize):
            raise PolicyError(f"{rid}: a post rule must `redact` or `neutralize` fields")
        if hook != "post" and (redact or neutralize):
            raise PolicyError(f"{rid}: only post rules change output")
        if hook in ("access", "pre") and not entry.get("reason"):
            raise PolicyError(f"{rid}: a denying rule needs a `reason`")
        rules.append(
            Rule(
                id=rid, hook=hook, tools=tuple(tools), when=dict(when), reason=entry.get("reason", ""),
                description=entry.get("description", ""), escalate=entry.get("escalate"), redact=redact,
                replacement=entry.get("replacement", "[REDACTED]"), neutralize=neutralize,
            )
        )
    return Policy(toolkit=toolkit, rules=tuple(rules))


def load_policy(path: Path | str = DEFAULT_POLICY) -> Policy:
    return parse_policy(json.loads(Path(path).read_text()))


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def show(value: Any) -> str:
    """A value as the reason text shows it: 95000, not 95000.0."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def render(template: str, facts: Mapping[str, Any]) -> str:
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: show(facts.get(m.group(1), m.group(0))), template)


@dataclass
class Facts:
    """What a pre rule can look at. `request` and `exposure` are read from the graph only if a rule asks."""

    user: str
    subject: Mapping[str, Any]
    inputs: Mapping[str, Any]
    request_lookup: Callable[[str], Mapping[str, Any] | None] = lambda _id: None
    exposure_lookup: Callable[[str], float] = lambda _loan: 0.0
    _request: Any = None
    _request_read: bool = False

    @property
    def clearance(self) -> float:
        return number(self.subject.get("clearance")) or 0.0

    @property
    def request(self) -> Mapping[str, Any] | None:
        if not self._request_read:
            request_id = self.inputs.get("request_id")
            self._request = self.request_lookup(str(request_id)) if request_id else None
            self._request_read = True
        return self._request

    def template_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {**self.inputs, "user": self.user, "clearance": self.clearance, "role": self.subject.get("role")}
        if self._request_read and self.request:
            values |= {
                "request_amount": self.request.get("amount"),
                "requested_by": self.request.get("requested_by"),
                "routed_to": self.request.get("routed_to"),
            }
        return values


def holds(rule: Rule, facts: Facts, extra: dict[str, Any]) -> bool:
    """Whether every condition of `rule` is true for these facts. `extra` collects values for the reason text."""
    for key, expected in rule.when.items():
        if key == "role_in":
            ok = facts.subject.get("role") in expected
        elif key == "clearance_below":
            ok = facts.clearance < expected
        elif key == "input_exceeds_clearance":
            amount = number(facts.inputs.get(expected))
            ok = amount is not None and amount > facts.clearance
        elif key == "group_exposure_exceeds_clearance":
            amount = number(facts.inputs.get(expected))
            loan_id = facts.inputs.get("loan_id")
            if amount is None or not loan_id:
                ok = False
            else:
                exposure = facts.exposure_lookup(str(loan_id)) + amount
                extra["exposure"] = exposure
                ok = exposure > facts.clearance
        elif key == "request_not_pending":
            request = facts.request
            ok = (request is None or request.get("status") != "pending") == expected
        elif key == "caller_is_requester":
            request = facts.request
            ok = request is not None and (str(request.get("requested_by", "")).lower() == facts.user) == expected
        elif key == "request_exceeds_clearance":
            request = facts.request
            amount = number(request.get("amount")) if request else None
            ok = amount is not None and (amount > facts.clearance) == expected
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


def hidden_tools(policy: Policy, subject: Mapping[str, Any], tools: list[str]) -> dict[str, Rule]:
    """The tools an access rule hides from this subject, with the rule that hides each."""
    facts = Facts(user=str(subject.get("email", "")), subject=subject, inputs={})
    hidden: dict[str, Rule] = {}
    for tool in tools:
        for rule in policy.for_hook("access", tool):
            if holds(rule, facts, {}):
                hidden[tool] = rule
                break
    return hidden


INSTRUCTION_MARKERS = re.compile(
    r"(system note|ignore (all |any )?(earlier|previous|prior) instructions?|do not mention this|"
    r"you are an? (ai|assistant|model)|automated review)",
    re.IGNORECASE,
)
REMOVED = "[removed by policy: text addressed to an AI system]"


def neutralize_text(text: str) -> str:
    """Drop every paragraph that reads as an instruction to a model, keeping the rest of the note.

    A keyword heuristic, enough to show where the control sits. A production control plane would
    put a classifier here; the hook point is the same.
    """
    paragraphs = re.split(r"\n\s*\n", text)
    kept = [p for p in paragraphs if not INSTRUCTION_MARKERS.search(p)]
    if len(kept) == len(paragraphs):
        return text
    return "\n\n".join([*kept, REMOVED])


def apply_post(policy: Policy, tool: str, subject: Mapping[str, Any], output: Any) -> tuple[Any, list[tuple[Rule, list[str]]]]:
    """The output with every post rule that holds applied, and which fields each rule changed."""
    facts = Facts(user=str(subject.get("email", "")), subject=subject, inputs={})
    applied: list[tuple[Rule, list[str]]] = []
    for rule in policy.for_hook("post", tool):
        if not holds(rule, facts, {}):
            continue
        changed: list[str] = []

        def walk(node: Any, path: str = "") -> Any:
            if isinstance(node, dict):
                out = {}
                for key, value in node.items():
                    here = f"{path}.{key}" if path else key
                    if key in rule.redact and value is not None and value != rule.replacement:
                        out[key] = rule.replacement
                        changed.append(here)
                    elif key in rule.neutralize and isinstance(value, str):
                        cleaned = neutralize_text(value)
                        if cleaned != value:
                            changed.append(here)
                        out[key] = cleaned
                    else:
                        out[key] = walk(value, here)
                return out
            if isinstance(node, list):
                return [walk(item, f"{path}[{i}]") for i, item in enumerate(node)]
            return node

        output = walk(output)
        if changed:
            applied.append((rule, changed))
    return output, applied
