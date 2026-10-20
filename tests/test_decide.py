"""The decide step (Policy), broken checks, and running totals."""

from __future__ import annotations

from typing import Any

import pytest

from evalharness import EvalRequest, EvalResult, Finding, Session, Step
from evalharness.hooks import Event, Hooks, Moment, OnFail, Policy, Redact, check
from evalharness.state import MemoryStore, StateStore, limit_total


class Fixed:
    """A check that answers whatever it's given: for testing the decide step."""

    name, version, provider, speed, expected_ms = "pii", "1", "test", "inline", 1.0
    needs: frozenset[str] = frozenset()

    def __init__(self, result: EvalResult) -> None:
        self.result = result

    def evaluate(self, request: EvalRequest) -> EvalResult:
        return self.result


def result(verdict: str, *findings: Finding) -> EvalResult:
    return EvalResult(verdict, None, None, None, "r", "pii", "1", "test", findings=findings)  # type: ignore[arg-type]


TEXT = "Mail me at a@b.com or call 98765 43210."
EMAIL = Finding("EMAIL_ADDRESS", 0.9, start=11, end=18)
PHONE = Finding("PHONE_NUMBER", 0.8, start=27, end=38)


@pytest.mark.parametrize(
    ("policy", "given", "action", "text"),
    [
        (OnFail(), result("fail", EMAIL), "block", None),
        (OnFail(), result("pass"), "allow", None),
        (
            Redact(),
            result("fail", EMAIL, PHONE),
            "modify",
            "Mail me at [EMAIL_ADDRESS] or call [PHONE_NUMBER].",
        ),
        (
            Redact(),
            result("fail", PHONE, EMAIL),
            "modify",
            "Mail me at [EMAIL_ADDRESS] or call [PHONE_NUMBER].",
        ),
        (
            Redact(),
            result("fail", EMAIL, Finding("URL", 0.5, start=13, end=16)),
            "modify",
            "Mail me at [EMAIL_ADDRESS] or call 98765 43210.",
        ),  # a hit inside another
        # what Presidio really answered: a short "URL" starting where the email starts
        (
            Redact(),
            result("fail", Finding("URL", 0.5, start=11, end=14), EMAIL),
            "modify",
            "Mail me at [EMAIL_ADDRESS] or call 98765 43210.",
        ),
        (Redact(), result("fail", Finding("TOXIC", 0.9)), "block", None),  # nothing located
        (Redact(), result("pass"), "allow", None),
    ],
)
def test_the_decide_step(policy: Policy, given: EvalResult, action: str, text: str | None) -> None:
    hooks = Hooks()
    hooks.add("reply", check(Fixed(given), policy=policy))  # type: ignore[arg-type]
    decision = hooks.run(Event("reply", text=TEXT))
    assert (decision.action, decision.text) == (action, text)


@pytest.mark.parametrize(("on_error", "action"), [("closed", "block"), ("open", "allow")])
def test_a_check_that_answers_error_counts_as_broken(on_error: Any, action: str) -> None:
    records: list[Any] = []
    hooks = Hooks(moments={"pre_tool": Moment(on_error=on_error)}, on_record=records.append)
    hooks.add("pre_tool", check(Fixed(result("error"))))  # type: ignore[arg-type]
    assert hooks.run(Event("pre_tool", tool="issue_refund")).action == action
    assert records[0].broke


DAY = 86400.0


@pytest.mark.parametrize(
    ("past", "amount", "user", "action"),
    [
        ([], 15000, "C1", "allow"),
        ([15000], 4000, "C1", "allow"),  # 19,000 of 20,000
        ([15000], 6000, "C1", "escalate"),  # 21,000
        ([15000], 6000, "C2", "allow"),  # someone else's total
        ([15000], 6000, "", "allow"),  # no customer named: nothing to key on
    ],
)
def test_a_running_total_per_customer(
    past: list[float], amount: float, user: str, action: str
) -> None:
    now = [1000 * DAY]
    store = MemoryStore(clock=lambda: now[0])
    assert isinstance(store, StateStore)
    before, after = limit_total(
        store,
        tool="issue_refund",
        field="amount",
        max_total=20000,
        window_s=30 * DAY,
        name="refund_total",
    )
    hooks = Hooks()
    hooks.add("pre_tool", before, tools=["issue_refund"])
    hooks.add("post_tool", after, tools=["issue_refund"])
    for a in past:
        hooks.run(
            Event(
                "post_tool",
                tool="issue_refund",
                arguments={"amount": a},
                user="C1",
                result={"refunded": a},
            )
        )
    assert (
        hooks.run(
            Event("pre_tool", tool="issue_refund", arguments={"amount": amount}, user=user)
        ).action
        == action
    )


def test_old_refunds_fall_out_of_the_window() -> None:
    now = [0.0]
    store = MemoryStore(clock=lambda: now[0])
    store.add("k", 15000)
    now[0] = 31 * DAY
    assert store.total("k", 30 * DAY) == 0
    store.add("k", 100)
    assert store.total("k", 30 * DAY) == 100
    store.forget_before(DAY)
    assert store.entries["k"] == [(31 * DAY, 100)]


def test_a_failed_refund_is_not_counted() -> None:
    store = MemoryStore(clock=lambda: 0.0)
    _, after = limit_total(store, tool="t", field="amount", max_total=1, window_s=DAY)
    after(
        Event("post_tool", tool="t", arguments={"amount": 5}, user="C1", result={"is_error": True})
    )
    assert store.total("t_amount_limit:C1", DAY) == 0


def test_a_session_check_still_judges_before_the_call() -> None:
    from evalharness.patterns import RequiresBefore

    hooks = Hooks()
    hooks.add("pre_tool", check(RequiresBefore(action="issue_refund", before="get_order")))
    event = Event("pre_tool", tool="issue_refund", session=Session("s", (Step("user", text="r"),)))
    assert hooks.run(event).action == "block"
