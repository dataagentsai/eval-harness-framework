"""The weekly report: counts over verdicts, the same every time."""

from __future__ import annotations

from typing import Any

import pytest

from evalharness.report import RuleLine, Verdict, to_html, weekly

DAY = 86400.0
START, END = 10 * DAY, 17 * DAY


def v(rule: str, label: str, at: float = START + DAY, **more: Any) -> Verdict:
    check = {"payout_approval": "decision_vs_should", "facts": "consistency"}.get(
        rule, "requires_before"
    )
    return Verdict(at=at, rule=rule, check=check, label=label, **more)


WEEK = [
    v("payout_approval", "pass"),
    v("payout_approval", "pass"),
    v(
        "payout_approval",
        "fail",
        finding_kinds=("under",),
        requirements=("P-PAYOUT",),
        session="c1",
    ),
    v("payout_approval", "not_applicable"),
    v("facts", "skip"),
    v(
        "facts",
        "fail",
        finding_kinds=("unsupported_fact",),
        requirements=("P-CLAIM-STATUS", "P-PAYOUT"),
    ),
    v("payout_approval", "fail", synthetic=True, finding_kinds=("under",)),  # a test conversation
    v("payout_approval", "fail", at=END + DAY, finding_kinds=("under",)),  # next week
]
BEFORE = [
    v("payout_approval", "pass", at=START - DAY),
    v("payout_approval", "pass", at=START - DAY),
]


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("verdicts", 6),  # the synthetic one and next week's left out
        ("unjudged", 1),
        ("requirements", {"P-PAYOUT": 2, "P-CLAIM-STATUS": 1}),
        ("unnamed", 0),
    ],
)
def test_the_week_is_counted(field: str, expected: Any) -> None:
    assert getattr(weekly(WEEK, start=START, end=END, previous=BEFORE), field) == expected


def test_rules_count_apart_and_rate_only_what_was_judged() -> None:
    report = weekly(WEEK, start=START, end=END, previous=BEFORE)
    approval = next(r for r in report.rules if r.rule == "payout_approval")
    assert approval.counts == {"pass": 2, "fail": 1, "not_applicable": 1}
    assert approval.fail_rate == pytest.approx(1 / 3)  # not_applicable is not in the rate
    assert approval.change == "up 33 points"


@pytest.mark.parametrize(
    ("counts", "before", "change"),
    [
        ({"pass": 1}, {}, "no earlier week"),
        ({"not_applicable": 3}, {"pass": 1}, "nothing judged"),
        ({"pass": 1}, {"pass": 4}, "same"),
        ({"pass": 3, "fail": 1}, {"pass": 1, "fail": 1}, "down 25 points"),
    ],
)
def test_the_change_against_the_week_before(
    counts: dict[str, int], before: dict[str, int], change: str
) -> None:
    assert RuleLine("r", counts, before).change == change


@pytest.mark.parametrize(
    ("include_synthetic", "agent", "under"),
    [(False, "", 1), (True, "", 2), (False, "fnol", 0)],
)
def test_saved_questions_answer_from_the_verdicts(
    include_synthetic: bool, agent: str, under: int
) -> None:
    report = weekly(WEEK, start=START, end=END, include_synthetic=include_synthetic, agent=agent)
    assert len(report.questions["under_escalations"]) == under
    assert len(report.questions["unsupported_facts"]) == (0 if agent else 1)


def test_a_verdict_reads_back_from_event_attributes() -> None:
    got = Verdict.of(
        5.0,
        {
            "gen_ai.evaluation.name": "payout_approval",
            "gen_ai.evaluation.score.label": "fail",
            "evalharness.check": "decision_vs_should",
            "evalharness.finding_kinds": "under",
            "evalharness.requirements": "P-PAYOUT,issue_payout.authority.agent_when",
            "evalharness.synthetic": "True",  # App Insights keeps it as text
            "evalharness.agent": "fnol",
        },
        trace="t1",
    )
    assert got == Verdict(
        5.0,
        "payout_approval",
        "decision_vs_should",
        "fail",
        "",
        "t1",
        ("P-PAYOUT", "issue_payout.authority.agent_when"),
        ("under",),
        "fnol",
        True,
    )


def test_the_page_says_when_test_conversations_are_counted() -> None:
    real = to_html(weekly(WEEK, start=START, end=END))
    test = to_html(weekly(WEEK, start=START, end=END, include_synthetic=True))
    assert "test conversations" not in real and "test conversations" in test
    assert "<script" not in real and "P-PAYOUT" in real


def test_a_failure_whose_rule_names_no_requirement_is_counted_apart() -> None:
    report = weekly([v("payout_approval", "fail", finding_kinds=("under",))], start=START, end=END)
    assert (report.requirements, report.unnamed) == ({}, 1)
    assert "name no requirement" in to_html(report)
