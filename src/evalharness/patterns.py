"""The domain patterns: reusable session checks a domain team fills in with YAML.

    cancel_needs_lookup:
      adapter: requires_before
      action: cancel_order
      before: get_order
      same: [order_id]                 # the lookup must be for the same order

Each pattern is plain code over a `Session`: no judge model, no vendor, the
same answer every run. Each is an `Adapter` whose provider is `ours`, so it is
configured, run and reported exactly like Presidio or Azure: `call` returns
what was checked and what was found as JSON, and `from_provider` turns that
into one `EvalResult`. The score is the share of checked items that held
(1.0 when nothing applied); any violation fails the check, and each one is a
`Finding` saying what and where.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from evalharness.adapter import Adapter
from evalharness.core import EvalRequest, EvalResult, Finding, Scale, Session, Step

Found = dict[str, Any]


class Pattern(Adapter):
    version = "1"
    provider = "ours"
    needs = frozenset({"session"})
    carries = frozenset({"session"})
    speed = "online"
    expected_ms = 5
    default_scale = Scale(raw_min=0, raw_max=1, higher_is_better=True, threshold=1.0)

    def check(self, session: Session) -> tuple[int, list[Found]]:
        """How many items were checked, and each violation as `{kind, label, step}`;
        `step` (the index in `session.steps`) stays in the raw answer."""
        raise NotImplementedError

    def to_provider(self, request: EvalRequest) -> Session:
        assert request.session is not None
        return request.session

    def call(self, payload: Session) -> Mapping[str, Any]:
        checked, found = self.check(payload)
        return {"session": payload.id, "checked": checked, "findings": found}

    def from_provider(self, raw: Mapping[str, Any], request: EvalRequest) -> EvalResult:
        checked, found = int(raw["checked"]), list(raw["findings"])
        held = 1.0 if checked == 0 else max(0.0, 1.0 - len(found) / checked)
        reason = (
            "nothing to check"
            if checked == 0
            else f"{checked - len(found)} of {checked} held"
            + "".join(f"; {f['label']}" for f in found[:3])
        )
        return self.scored(
            held,
            reason=reason,
            findings=tuple(Finding(f["kind"], 1.0, severity=1.0, label=f["label"]) for f in found),
            raw=raw,
        )


# ------------------------------------------------------------------ 1 requires_before
class RequiresBefore(Pattern):
    """Every call to `action` needs an earlier, successful call to `before`,
    optionally with the same values for the argument names in `same`."""

    kind = "requires_before"

    def __init__(self, *, action: str, before: str, same: Sequence[str] = (), **base: Any) -> None:
        super().__init__(**base)
        self.action, self.before, self.same = action, before, tuple(same)

    def check(self, session: Session) -> tuple[int, list[Found]]:
        found: list[Found] = []
        actions = session.calls(self.action)
        for i, call in actions:
            if not any(
                j < i and session.succeeded(j) and self._same(call, prior)
                for j, prior in session.calls(self.before)
            ):
                found.append(
                    {
                        "kind": "missing_before",
                        "label": f"{self.action} without an earlier {self.before}"
                        + (f" for the same {', '.join(self.same)}" if self.same else ""),
                        "step": i,
                    }
                )
        return len(actions), found

    def _same(self, call: Step, prior: Step) -> bool:
        return all(call.arguments.get(k) == prior.arguments.get(k) for k in self.same)


# ------------------------------------------------------------------ 2 argument_limit
class ArgumentLimit(Pattern):
    """A tool argument must stay within `min` and `max` (a refund limit)."""

    kind = "argument_limit"

    def __init__(
        self,
        *,
        tool: str,
        field: str,
        max: float | None = None,  # noqa: A002 (the YAML's word)
        min: float | None = None,  # noqa: A002
        **base: Any,
    ) -> None:
        super().__init__(**base)
        self.tool, self.field, self.max, self.min = tool, field, max, min

    def check(self, session: Session) -> tuple[int, list[Found]]:
        found: list[Found] = []
        checked = 0
        for i, call in session.calls(self.tool):
            value = _number(call.arguments.get(self.field))
            if value is None:
                continue
            checked += 1
            if self.max is not None and value > self.max:
                found.append(self._over(i, value, "above", self.max))
            elif self.min is not None and value < self.min:
                found.append(self._over(i, value, "below", self.min))
        return checked, found

    def _over(self, step: int, value: float, side: str, limit: float) -> Found:
        return {
            "kind": "argument_limit",
            "label": f"{self.tool}.{self.field} = {value:g}, {side} {limit:g}",
            "step": step,
        }


# ------------------------------------------------------------------ 3 claim_needs_action
class ClaimNeedsAction(Pattern):
    """When a reply says something was done, the tool that does it must have
    been called successfully earlier in the session.

        claims:
          refund_issued: {phrases: ["refund has been issued"], tool: issue_refund}

    This is the deterministic version: it matches phrases, so a negated phrase
    ("your refund has not been issued yet") is a false alarm. The judge version,
    which first asks a model what the reply claims, comes later."""

    kind = "claim_needs_action"

    def __init__(self, *, claims: Mapping[str, Mapping[str, Any]], **base: Any) -> None:
        super().__init__(**base)
        self.claims = {
            name: (tuple(str(p).lower() for p in spec["phrases"]), str(spec["tool"]))
            for name, spec in claims.items()
        }

    def check(self, session: Session) -> tuple[int, list[Found]]:
        found: list[Found] = []
        checked = 0
        for i, step in enumerate(session.steps):
            if step.kind != "assistant":
                continue
            text = step.text.lower()
            for name, (phrases, tool) in self.claims.items():
                said = next((p for p in phrases if p in text), None)
                if said is None:
                    continue
                checked += 1
                if not any(j < i and session.succeeded(j) for j, _ in session.calls(tool)):
                    found.append(
                        {
                            "kind": "claim_not_backed",
                            "label": f"said “{said}” ({name}) but {tool} was not done",
                            "step": i,
                        }
                    )
        return checked, found


# ------------------------------------------------------------------ 4 decision_vs_should
class DecisionVsShould(Pattern):
    """Was a decision (such as escalating) made exactly when the rule says it
    should be? Over: made with no reason. Under: a reason, and not made.

        decision: escalate                  # a `decision` step with this name...
        decision_tool: hand_to_human        # ...or a call to this tool
        when:                               # any one of these means it should be made
          - {tool: issue_refund, field: amount, above: 25000}
          - {failed_calls_at_least: 3}
          - {user_says: ["speak to a human", "manager"]}
          - {tool_called: report_fraud}

    The yardstick here is a rule. A judge's or a human's label is a different
    source, reported as such when those arrive."""

    kind = "decision_vs_should"

    def __init__(
        self,
        *,
        decision: str,
        when: Sequence[Mapping[str, Any]],
        decision_tool: str | None = None,
        **base: Any,
    ) -> None:
        super().__init__(**base)
        self.decision, self.decision_tool, self.when = decision, decision_tool, tuple(when)
        for condition in self.when:
            if not set(condition) & {"tool", "failed_calls_at_least", "user_says", "tool_called"}:
                raise TypeError(f"unknown condition {dict(condition)}")

    def check(self, session: Session) -> tuple[int, list[Found]]:
        made = any(
            (s.kind == "decision" and s.name == self.decision)
            or (
                self.decision_tool is not None
                and s.kind == "tool_call"
                and s.name == self.decision_tool
            )
            for s in session.steps
        )
        reasons = [r for c in self.when if (r := self._holds(c, session))]
        if made and not reasons:
            return 1, [{"kind": "over", "label": f"{self.decision} with no rule calling for it"}]
        if reasons and not made:
            return 1, [{"kind": "under", "label": f"no {self.decision} although {reasons[0]}"}]
        return 1, []

    @staticmethod
    def _holds(condition: Mapping[str, Any], session: Session) -> str:
        if "tool" in condition:
            for _, call in session.calls(str(condition["tool"])):
                value = _number(call.arguments.get(str(condition["field"])))
                if value is not None and value > float(condition["above"]):
                    name = f"{condition['tool']}.{condition['field']}"
                    return f"{name} = {value:g} > {condition['above']}"
        if "failed_calls_at_least" in condition:
            failed = sum(1 for s in session.steps if s.kind == "tool_result" and s.is_error)
            if failed >= int(condition["failed_calls_at_least"]):
                return f"{failed} tool calls failed"
        if "user_says" in condition:
            for s in session.steps:
                if s.kind == "user":
                    said = next(
                        (p for p in condition["user_says"] if p.lower() in s.text.lower()), None
                    )
                    if said:
                        return f"the user said “{said}”"
        if "tool_called" in condition and session.calls(str(condition["tool_called"])):
            return f"{condition['tool_called']} was called"
        return ""


# ------------------------------------------------------------------ 5 consistency
class Consistency(Pattern):
    """Every fact of a named kind in a reply must appear in an earlier tool
    result: a claim id or an amount the agent states must come from a system.

        facts:
          claim_id: "CLM-\\\\d{6}"
          amount: "₹\\\\s?[\\\\d,]+"

    Values are compared after dropping everything but letters, digits and
    hyphens, so “₹12,400” in a reply matches 12400 in a result."""

    kind = "consistency"

    def __init__(self, *, facts: Mapping[str, str], **base: Any) -> None:
        super().__init__(**base)
        self.facts = {name: re.compile(pattern) for name, pattern in facts.items()}

    def check(self, session: Session) -> tuple[int, list[Found]]:
        found: list[Found] = []
        checked = 0
        known: set[str] = set()
        for i, step in enumerate(session.steps):
            if step.kind == "tool_result":
                known |= {_norm(v) for v in _scalars(step.result)}
                known |= {_norm(m) for p in self.facts.values() for m in p.findall(step.text)}
            elif step.kind == "assistant":
                for name, pattern in self.facts.items():
                    for value in pattern.findall(step.text):
                        checked += 1
                        if _norm(value) not in known:
                            found.append(
                                {
                                    "kind": "unsupported_fact",
                                    "label": f"{name} “{value}” is in no earlier tool result",
                                    "step": i,
                                }
                            )
        return checked, found


# ------------------------------------------------------------------ helpers
def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(re.sub(r"[^\d.\-]", "", value))
        except ValueError:
            return None
    return None


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z\-]", "", str(value)).lower()


def _scalars(value: object) -> Iterator[object]:
    if isinstance(value, Mapping):
        for v in value.values():
            yield from _scalars(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _scalars(v)
    elif isinstance(value, str) and value[:1] in "[{":
        try:
            yield from _scalars(json.loads(value))
        except ValueError:
            yield value
    elif value is not None:
        yield value


PATTERNS: dict[str, str] = {
    "argument_limit": "evalharness.patterns:ArgumentLimit",
    "claim_needs_action": "evalharness.patterns:ClaimNeedsAction",
    "consistency": "evalharness.patterns:Consistency",
    "decision_vs_should": "evalharness.patterns:DecisionVsShould",
    "requires_before": "evalharness.patterns:RequiresBefore",
}
