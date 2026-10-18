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
NEGATIONS: tuple[str, ...] = (
    "not",
    "n't",
    "no",
    "never",
    "nothing",
    "neither",
    "nor",
    "yet",
    "cannot",
    "unable",
    "nobody",
    "no one",
)
"""Words that make a sentence no claim (`claim_needs_action`), and no request
or report (`user_says`): "Nobody was hurt" does not report an injury."""


def _negation(negations: Sequence[str]) -> re.Pattern[str]:
    words = "|".join(re.escape(n) for n in negations if n != "n't")
    return re.compile(rf"\b(?:{words})\b" + (r"|n't\b" if "n't" in negations else ""), re.I)


NEGATED = _negation(NEGATIONS)


def _plain_sentences(text: str, negated: re.Pattern[str]) -> list[str]:
    """The sentences of `text` that are neither questions nor negated, lowercased."""
    return [
        t.lower()
        for t in re.split(r"(?<=[.!?])\s+", text)
        if not t.rstrip().endswith("?") and not negated.search(t)
    ]


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

    This is the deterministic version: it matches phrases, sentence by sentence,
    and skips a sentence that is a question or carries a negation word
    (`negations`). Run on FNOL's scenarios before the guard, every finding was a
    negation ("Nothing has been paid yet"). The guard trades those false alarms
    for a miss in a mixed sentence ("Your refund has been issued, not the
    replacement"); the judge version, which asks a model what the reply claims,
    comes later."""

    kind = "claim_needs_action"

    def __init__(
        self,
        *,
        claims: Mapping[str, Mapping[str, Any]],
        negations: Sequence[str] = NEGATIONS,
        **base: Any,
    ) -> None:
        super().__init__(**base)
        self.negated = _negation(negations)
        self.claims = {
            name: (tuple(str(p).lower() for p in spec["phrases"]), str(spec["tool"]))
            for name, spec in claims.items()
        }

    def check(self, session: Session) -> tuple[int, list[Found]]:
        found: list[Found] = []
        checked = 0
        for i, step in enumerate(session.steps):
            if not step.by_agent:
                continue
            sentences = _plain_sentences(step.text, self.negated)
            for name, (phrases, tool) in self.claims.items():
                said = next((p for p in phrases for t in sentences if p in t), None)
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
    """Was a decision (escalating, asking for approval) made exactly when the
    rules say it should be? Judged per window: the steps since the previous
    such decision, so what came before a person handed the conversation back
    does not count toward the next hand-over.

        decision: awaiting_human            # a `decision` step with this name...
        decision_tool: hand_to_human        # ...or a call to this tool
        check: both                         # both · under · over
        when:                               # any one of these means it should be made
          - {user_says: ["speak to a person"]}
          - {consecutive_failed_at_least: 2}
          - {failed_calls_at_least: 3}
          - {tool: issue_payout, field: amount, above: 25000}
          - {tool_called: report_fraud}
          - {result_of: get_order, field: total, above: 10000}
          - {result_of: get_order, field: status, not_in: [returned]}
          - all:                            # every one of these at once
              - {tool_called: request_refund}
              - {result_of: get_order, field: status, in: [delivered]}

    Over (made with no reason in its window) can only be judged when `when`
    holds every trigger the agent's spec has; with some of them, set
    `check: under`, or a hand-over for a reason not listed reads as needless.
    The yardstick is a rule; a judge's or a human's label is another source."""

    kind = "decision_vs_should"

    def __init__(
        self,
        *,
        decision: str,
        when: Sequence[Mapping[str, Any]],
        decision_tool: str | None = None,
        check: str = "both",
        **base: Any,
    ) -> None:
        super().__init__(**base)
        if check not in ("both", "under", "over"):
            raise TypeError(f"check must be both, under or over, not {check!r}")
        self.decision, self.decision_tool, self.when = decision, decision_tool, tuple(when)
        self.check_over, self.check_under = check in ("both", "over"), check in ("both", "under")
        for condition in self.when:
            _known(condition)

    def _made(self, step: Step) -> bool:
        return (step.kind == "decision" and step.name == self.decision) or (
            self.decision_tool is not None
            and step.kind == "tool_call"
            and step.name == self.decision_tool
        )

    def check(self, session: Session) -> tuple[int, list[Found]]:
        found: list[Found] = []
        windows, start = 0, 0
        for i, step in enumerate(session.steps):
            if not self._made(step):
                continue
            windows += 1
            window = session.steps[start:i]
            if self.check_over and not self._reason(window):
                found.append(
                    {
                        "kind": "over",
                        "label": f"{self.decision} with no rule calling for it",
                        "step": i,
                    }
                )
            start = i + 1
        rest = session.steps[start:]
        if rest or windows == 0:
            windows += 1
            reason = self._reason(rest)
            if self.check_under and reason:
                found.append(
                    {
                        "kind": "under",
                        "label": f"no {self.decision} although {reason}",
                        "step": len(session.steps),
                    }
                )
        return windows, found

    def _reason(self, window: Sequence[Step]) -> str:
        return next((r for c in self.when if (r := _holds(c, window))), "")


def _holds(condition: Mapping[str, Any], steps: Sequence[Step]) -> str:
    """Why `condition` holds over `steps`, or "" when it does not."""
    if "all" in condition:
        reasons = [_holds(c, steps) for c in condition["all"]]
        return " and ".join(reasons) if all(reasons) else ""
    calls = [s for s in steps if s.kind == "tool_call"]
    results = [s for s in steps if s.kind == "tool_result"]
    if "result_of" in condition:
        for step in results:
            if step.is_error or step.name != condition["result_of"]:
                continue
            value = (
                step.result.get(str(condition["field"]))
                if isinstance(step.result, Mapping)
                else None
            )
            name = f"{condition['result_of']} returned {condition['field']} = {value}"
            if "above" in condition:
                number = _number(value)
                if number is not None and number > float(condition["above"]):
                    return name
            elif "in" in condition:
                if value in condition["in"]:
                    return name
            elif "not_in" in condition and value is not None and value not in condition["not_in"]:
                return name
    if "tool" in condition:
        for call in calls:
            if call.name != condition["tool"]:
                continue
            number = _number(call.arguments.get(str(condition["field"])))
            if number is not None and number > float(condition["above"]):
                return (
                    f"{condition['tool']}.{condition['field']} = {number:g} > {condition['above']}"
                )
    if "failed_calls_at_least" in condition:
        failed = sum(1 for s in results if s.is_error)
        if failed >= int(condition["failed_calls_at_least"]):
            return f"{failed} tool calls failed"
    if "consecutive_failed_at_least" in condition:
        run = longest = 0
        for s in results:
            run = run + 1 if s.is_error else 0
            longest = max(longest, run)
        if longest >= int(condition["consecutive_failed_at_least"]):
            return f"{longest} tool calls failed in a row"
    if "user_says" in condition:
        for s in steps:
            if s.kind != "user":
                continue
            plain = _plain_sentences(s.text, NEGATED)
            said = next((p for p in condition["user_says"] for t in plain if p.lower() in t), None)
            if said:
                return f"the user said “{said}”"
    if "tool_called" in condition and any(c.name == condition["tool_called"] for c in calls):
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
    hyphens, so “₹12,400” in a reply matches 12400 in a result. With
    `from_user` (the default), what the customer said counts as known too:
    repeating the customer's own claim id back is not inventing it."""

    kind = "consistency"

    def __init__(self, *, facts: Mapping[str, str], from_user: bool = True, **base: Any) -> None:
        super().__init__(**base)
        self.facts = {name: re.compile(pattern) for name, pattern in facts.items()}
        self.from_user = from_user

    def check(self, session: Session) -> tuple[int, list[Found]]:
        found: list[Found] = []
        checked = 0
        known: set[str] = set()
        for i, step in enumerate(session.steps):
            if step.kind == "user" and self.from_user:
                known |= {_norm(m) for p in self.facts.values() for m in p.findall(step.text)}
            elif step.kind == "tool_result":
                known |= {_norm(v) for v in _scalars(step.result)}
                known |= {_norm(m) for p in self.facts.values() for m in p.findall(step.text)}
            elif step.by_agent:
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
CONDITIONS = {
    "tool",
    "failed_calls_at_least",
    "consecutive_failed_at_least",
    "user_says",
    "tool_called",
    "result_of",
    "all",
}


def _known(condition: Mapping[str, Any]) -> None:
    if not set(condition) & CONDITIONS:
        raise TypeError(f"unknown condition {dict(condition)}")
    for inner in condition.get("all", ()):
        _known(inner)


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
