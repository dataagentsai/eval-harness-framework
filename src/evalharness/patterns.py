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
from evalharness.facts import fact_type

Found = dict[str, Any]
UNJUDGED = "unjudged"
"""The kind of an item a check could not judge, because the session did not record what it needs."""


def _unjudged(label: str, step: int) -> Found:
    return {"kind": UNJUDGED, "label": label, "step": step}


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
        `step` (the index in `session.steps`) stays in the raw answer. An item
        that needs what the session did not record is not checked: it is listed
        with kind `unjudged`, never counted as a pass or a fail."""
        raise NotImplementedError

    def to_provider(self, request: EvalRequest) -> Session:
        assert request.session is not None
        return request.session

    def call(self, payload: Session) -> Mapping[str, Any]:
        checked, found = self.check(payload)
        return {"session": payload.id, "checked": checked, "findings": found}

    def from_provider(self, raw: Mapping[str, Any], request: EvalRequest) -> EvalResult:
        checked, every = int(raw["checked"]), list(raw["findings"])
        found = [f for f in every if f["kind"] != UNJUDGED]
        unjudged = [f for f in every if f["kind"] == UNJUDGED]
        if checked == 0 and unjudged:
            return self.result("skip", reason=f"could not judge: {unjudged[0]['label']}", raw=raw)
        held = 1.0 if checked == 0 else max(0.0, 1.0 - len(found) / checked)
        reason = (
            "nothing to check"
            if checked == 0
            else f"{checked - len(found)} of {checked} held"
            + "".join(f"; {f['label']}" for f in found[:3])
            + (f"; {len(unjudged)} not judged: {unjudged[0]['label']}" if unjudged else "")
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
        checked = 0
        blind = bool(self.same) and "arguments" in session.unrecorded
        for i, call in session.calls(self.action):
            priors = [p for j, p in session.calls(self.before) if j < i and session.succeeded(j)]
            if priors and blind:  # a lookup happened; whether for the same one is unknown
                found.append(
                    _unjudged(
                        f"arguments not recorded, so “same {', '.join(self.same)}” "
                        f"can't be checked for {self.action}",
                        i,
                    )
                )
                continue
            checked += 1
            if not any(self._same(call, prior) for prior in priors):
                found.append(
                    {
                        "kind": "missing_before",
                        "label": f"{self.action} without an earlier {self.before}"
                        + (f" for the same {', '.join(self.same)}" if self.same else ""),
                        "step": i,
                    }
                )
        return checked, found

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
            if "arguments" in session.unrecorded and self.field not in call.arguments:
                found.append(
                    _unjudged(f"arguments not recorded, so {self.tool}.{self.field} is unknown", i)
                )
                continue
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
    obligations = ("AAC-0110",)

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
        if "text" in session.unrecorded and not any(s.by_agent for s in session.steps):
            return 0, [_unjudged("the agent's replies were not recorded", len(session.steps))]
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
    obligations = ("AAC-0078", "AAC-0043")

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
        windows, start, made = 0, 0, 0
        unrecorded = session.unrecorded
        for i, step in enumerate(session.steps):
            if not self._made(step):
                continue
            made += 1
            window = session.steps[start:i]
            start = i + 1
            state, reason = _any(self.when, window, unrecorded)
            if self.check_over and state == UNKNOWN:
                found.append(
                    _unjudged(
                        f"{self.decision} made; whether a rule called for it is unknown ({reason})",
                        i,
                    )
                )
                continue
            windows += 1
            if self.check_over and state == NO:
                found.append(
                    {
                        "kind": "over",
                        "label": f"{self.decision} with no rule calling for it",
                        "step": i,
                    }
                )
        rest = session.steps[start:]
        if rest or made == 0:
            state, reason = _any(self.when, rest, unrecorded)
            if self.check_under and state == UNKNOWN:
                found.append(
                    _unjudged(
                        f"whether {self.decision} was due is unknown ({reason})", len(session.steps)
                    )
                )
                return windows, found
            windows += 1
            if self.check_under and state == YES:
                found.append(
                    {
                        "kind": "under",
                        "label": f"no {self.decision} although {reason}",
                        "step": len(session.steps),
                    }
                )
        return windows, found


YES, NO, UNKNOWN = "yes", "no", "unknown"
NEEDS = {"result_of": "results", "user_says": "text", "tool": "arguments"}
"""What each condition reads that a source may not have recorded."""


def _any(
    when: Sequence[Mapping[str, Any]], steps: Sequence[Step], unrecorded: frozenset[str]
) -> tuple[str, str]:
    """Whether any condition holds: yes with its reason, no, or unknown with why."""
    unknown = ""
    for condition in when:
        state, reason = _eval(condition, steps, unrecorded)
        if state == YES:
            return YES, reason
        if state == UNKNOWN and not unknown:
            unknown = reason
    return (UNKNOWN, unknown) if unknown else (NO, "")


def _eval(
    condition: Mapping[str, Any], steps: Sequence[Step], unrecorded: frozenset[str]
) -> tuple[str, str]:
    """A condition over `steps`, in three values: what was not recorded can't
    make it false."""
    if "all" in condition:
        parts = [_eval(c, steps, unrecorded) for c in condition["all"]]
        if any(state == NO for state, _ in parts):
            return NO, ""
        if all(state == YES for state, _ in parts):
            return YES, " and ".join(r for _, r in parts)
        return UNKNOWN, next(r for state, r in parts if state == UNKNOWN)
    reason = _holds(condition, steps)
    if reason:
        return YES, reason
    for key, needs in NEEDS.items():
        if key in condition and needs in unrecorded and _relevant(key, condition, steps):
            return (
                UNKNOWN,
                f"{'customer words' if needs == 'text' else 'tool ' + needs} not recorded",
            )
    return NO, ""


def _relevant(key: str, condition: Mapping[str, Any], steps: Sequence[Step]) -> bool:
    """Whether unrecorded data could have made the condition true here: a tool
    result only matters if that tool ran and succeeded; arguments only if that
    tool was called; the customer's words always (unrecorded words leave no
    step behind, so an empty window may still have had a customer speaking)."""
    if key == "result_of":
        return any(
            s.kind == "tool_result" and s.name == condition["result_of"] and not s.is_error
            for s in steps
        )
    if key == "tool":
        return any(s.kind == "tool_call" and s.name == condition["tool"] for s in steps)
    return True


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
          claim_id: {shape: "CLM-######"}
          amount: inr_amount

    Each kind is a fact type (`evalharness.facts`): a built-in type, a shape,
    or a regular expression. Values are compared the type's way, so an amount
    in rupees matches the same number in a result however it is written. With
    `from_user` (the default), what the customer said counts as known too:
    repeating the customer's own claim id back is not inventing it."""

    kind = "consistency"
    obligations = ("AAC-0029",)

    def __init__(
        self, *, facts: Mapping[str, str | Mapping[str, Any]], from_user: bool = True, **base: Any
    ) -> None:
        super().__init__(**base)
        self.facts = {name: fact_type(name, spec) for name, spec in facts.items()}
        self.from_user = from_user

    def check(self, session: Session) -> tuple[int, list[Found]]:
        found: list[Found] = []
        checked = 0
        known: dict[str, set[str]] = {name: set() for name in self.facts}
        if "text" in session.unrecorded and not any(s.by_agent for s in session.steps):
            return 0, [_unjudged("the agent's replies were not recorded", len(session.steps))]

        def learn(texts: list[str]) -> None:
            for name, kind in self.facts.items():
                for text in texts:
                    known[name] |= {n for v in kind.find(text) if (n := kind.normalise(v))}
                    whole = kind.normalise(text)
                    if whole:
                        known[name].add(whole)

        for i, step in enumerate(session.steps):
            if step.kind == "user" and self.from_user:
                learn([step.text])
            elif step.kind == "tool_result":
                learn([str(v) for v in _scalars(step.result)] + [step.text])
            elif step.by_agent:
                for name, kind in self.facts.items():
                    for value in kind.find(step.text):
                        checked += 1
                        if kind.normalise(value) not in known[name]:
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
