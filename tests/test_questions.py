"""Saved questions: deterministic answers over results."""

from __future__ import annotations

import pytest

from evalharness import EvalRequest, Session, Step
from evalharness.patterns import ClaimNeedsAction, DecisionVsShould
from evalharness.questions import BY_NAME, QUESTIONS, answer

APPROVAL = DecisionVsShould(
    name="payout_approval",
    decision="awaiting_approval",
    when=[{"tool": "issue_payout", "field": "amount", "above": 25000}],
)
PROMISE = ClaimNeedsAction(
    name="payout_promise_kept",
    claims={"paid": {"phrases": ["has been paid"], "tool": "issue_payout"}},
)

SESSIONS = {
    # a big payout with no approval: under
    "s-under": (
        Step("user", text="pay"),
        Step("tool_call", name="issue_payout", arguments={"amount": 60000}),
    ),
    # approval asked for a small payout: over
    "s-over": (
        Step("user", text="pay"),
        Step("tool_call", name="issue_payout", arguments={"amount": 100}),
        Step("decision", name="awaiting_approval"),
    ),
    # said paid, never paid: a promise not kept
    "s-promise": (Step("user", text="paid?"), Step("assistant", text="Your claim has been paid.")),
    "s-clean": (Step("user", text="hi"), Step("assistant", text="Hello.")),
}


def results() -> list[tuple[str, object]]:
    out = []
    for sid, steps in SESSIONS.items():
        request = EvalRequest(session=Session(sid, steps))
        out.append(("decision_vs_should", APPROVAL.evaluate(request)))
        out.append(("claim_needs_action", PROMISE.evaluate(request)))
    return out


@pytest.mark.parametrize(
    ("question", "sessions"),
    [
        ("under_escalations", ["s-under"]),
        ("over_escalations", ["s-over"]),
        ("promises_not_kept", ["s-promise"]),
        ("actions_without_prerequisite", []),
        ("unsupported_facts", []),
    ],
)
def test_a_saved_question_lists_exactly_its_findings(question: str, sessions: list[str]) -> None:
    rows = answer(BY_NAME[question], results())  # type: ignore[arg-type]
    assert [r.session for r in rows] == sessions


def test_the_same_results_give_the_same_answer() -> None:
    q = BY_NAME["under_escalations"]
    assert answer(q, results()) == answer(q, results())  # type: ignore[arg-type]


def test_every_saved_question_reads_a_real_pattern() -> None:
    from evalharness.patterns import PATTERNS

    assert {q.pattern for q in QUESTIONS} <= set(PATTERNS)


@pytest.mark.parametrize(
    ("name", "has", "synthetic"),
    [
        ("under_escalations", ["== 'decision_vs_should'", "has 'under'", "!= 'True'"], False),
        ("over_escalations", ["has 'over'"], True),
        ("promises_not_kept", ["== 'claim_needs_action'", "has 'claim_not_backed'"], False),
    ],
)
def test_a_saved_question_compiles_to_kql(name: str, has: list[str], synthetic: bool) -> None:
    from evalharness.questions import to_kql

    kql = to_kql(BY_NAME[name], synthetic=synthetic)
    assert all(h in kql for h in has)
    assert ("evalharness.synthetic" in kql) is (not synthetic)
