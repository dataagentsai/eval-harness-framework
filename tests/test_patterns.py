"""The five domain patterns, the session shape, and presets."""

from __future__ import annotations

from typing import Any

import pytest

from evalharness import EvalRequest, Session, Step
from evalharness.config import ConfigRefused, build, with_preset
from evalharness.patterns import (
    PATTERNS,
    ArgumentLimit,
    ClaimNeedsAction,
    Consistency,
    DecisionVsShould,
    Pattern,
    RequiresBefore,
)

JUDGE = {"model": "m", "base_url": "http://judge.invalid", "api_key_env": "NO_SUCH_KEY"}


def user(text: str) -> Step:
    return Step("user", text=text)


def say(text: str) -> Step:
    return Step("assistant", text=text)


def call(name: str, cid: str = "", **arguments: Any) -> Step:
    return Step("tool_call", name=name, arguments=arguments, call_id=cid)


def ok(name: str, result: object = None, cid: str = "") -> Step:
    return Step("tool_result", name=name, result=result, call_id=cid)


def failed(name: str, cid: str = "") -> Step:
    return Step("tool_result", name=name, is_error=True, call_id=cid)


def judged(pattern: Pattern, *steps: Step) -> tuple[str, float | None, list[str]]:
    result = pattern.evaluate(EvalRequest(session=Session("s1", steps)))
    return result.verdict, result.score, [f.kind for f in result.findings]


# ------------------------------------------------------------------ requires_before
CANCEL = RequiresBefore(action="cancel_order", before="get_order", same=["order_id"])
REQUIRES = [
    (
        "looked up first",
        [call("get_order", order_id=7), ok("get_order"), call("cancel_order", order_id=7)],
        "pass",
        1.0,
    ),
    ("never looked up", [call("cancel_order", order_id=7)], "fail", 0.0),
    (
        "looked up a different order",
        [call("get_order", order_id=8), ok("get_order"), call("cancel_order", order_id=7)],
        "fail",
        0.0,
    ),
    (
        "lookup failed",
        [call("get_order", order_id=7), failed("get_order"), call("cancel_order", order_id=7)],
        "fail",
        0.0,
    ),
    (
        "lookup came after",
        [call("cancel_order", order_id=7), call("get_order", order_id=7), ok("get_order")],
        "fail",
        0.0,
    ),
    (
        "one of two cancels unbacked",
        [
            call("get_order", order_id=7),
            ok("get_order"),
            call("cancel_order", order_id=7),
            call("cancel_order", order_id=9),
        ],
        "fail",
        0.5,
    ),
    ("no cancel at all", [call("get_order", order_id=7), ok("get_order")], "pass", 1.0),
]


@pytest.mark.parametrize(
    ("name", "steps", "verdict", "score"), REQUIRES, ids=[r[0] for r in REQUIRES]
)
def test_requires_before(name: str, steps: list[Step], verdict: str, score: float) -> None:
    assert judged(CANCEL, *steps)[:2] == (verdict, score)


def test_a_result_is_paired_by_call_id_where_recorded() -> None:
    steps = [
        call("get_order", "c1", order_id=7),
        call("get_order", "c2", order_id=7),
        ok("get_order", cid="c2"),
        failed("get_order", cid="c1"),
        call("cancel_order", order_id=7),
    ]
    assert judged(CANCEL, *steps)[0] == "pass"  # c2 succeeded, whatever the order


# ------------------------------------------------------------------ argument_limit
REFUND = ArgumentLimit(tool="issue_refund", field="amount", max=5000)
LIMITS = [
    ("within", [call("issue_refund", amount=4999)], "pass", []),
    ("at the limit", [call("issue_refund", amount=5000)], "pass", []),
    ("over", [call("issue_refund", amount=5001)], "fail", ["argument_limit"]),
    (
        "over, as text with a symbol",
        [call("issue_refund", amount="₹12,400")],
        "fail",
        ["argument_limit"],
    ),
    ("field missing: not checked", [call("issue_refund", reason="dup")], "pass", []),
    ("another tool", [call("issue_payout", amount=90000)], "pass", []),
]


@pytest.mark.parametrize(("name", "steps", "verdict", "kinds"), LIMITS, ids=[r[0] for r in LIMITS])
def test_argument_limit(name: str, steps: list[Step], verdict: str, kinds: list[str]) -> None:
    got = judged(REFUND, *steps)
    assert (got[0], got[2]) == (verdict, kinds)


def test_a_minimum_too() -> None:
    assert judged(ArgumentLimit(tool="t", field="n", min=1), call("t", n=0))[0] == "fail"


# ------------------------------------------------------------------ claim_needs_action
PROMISE = ClaimNeedsAction(
    claims={
        "refund_issued": {"phrases": ["refund has been issued", "refunded"], "tool": "issue_refund"}
    }
)
CLAIMS = [
    (
        "said and done",
        [call("issue_refund"), ok("issue_refund"), say("Your refund has been issued.")],
        "pass",
    ),
    ("said, never done", [say("Your refund has been issued.")], "fail"),
    (
        "said, tool failed",
        [call("issue_refund"), failed("issue_refund"), say("You've been refunded.")],
        "fail",
    ),
    (
        "done after saying it",
        [say("Refund has been issued!"), call("issue_refund"), ok("issue_refund")],
        "fail",
    ),
    ("nothing claimed", [say("I can look into a refund for you.")], "pass"),
]


@pytest.mark.parametrize(("name", "steps", "verdict"), CLAIMS, ids=[r[0] for r in CLAIMS])
def test_claim_needs_action(name: str, steps: list[Step], verdict: str) -> None:
    assert judged(PROMISE, *steps)[0] == verdict


def test_the_deterministic_version_is_fooled_by_negation_as_documented() -> None:
    assert judged(PROMISE, say("I can't confirm your refund has been issued yet."))[0] == "fail"


# ------------------------------------------------------------------ decision_vs_should
ESCALATE = DecisionVsShould(
    decision="escalate",
    decision_tool="hand_to_human",
    when=[
        {"tool": "issue_payout", "field": "amount", "above": 25000},
        {"failed_calls_at_least": 3},
        {"user_says": ["speak to a human"]},
    ],
)
ESCALATIONS = [
    (
        "big payout, escalated",
        [call("issue_payout", amount=40000), Step("decision", name="escalate")],
        "pass",
        [],
    ),
    ("big payout, not escalated", [call("issue_payout", amount=40000)], "fail", ["under"]),
    (
        "asked for a human, handed over by tool",
        [user("Let me speak to a human"), call("hand_to_human")],
        "pass",
        [],
    ),
    ("asked for a human, ignored", [user("I want to speak to a human now")], "fail", ["under"]),
    ("three failures, not escalated", [failed("a"), failed("b"), failed("c")], "fail", ["under"]),
    (
        "small payout, escalated anyway",
        [call("issue_payout", amount=900), Step("decision", name="escalate")],
        "fail",
        ["over"],
    ),
    ("small payout, not escalated", [call("issue_payout", amount=900)], "pass", []),
]


@pytest.mark.parametrize(
    ("name", "steps", "verdict", "kinds"), ESCALATIONS, ids=[r[0] for r in ESCALATIONS]
)
def test_decision_vs_should(name: str, steps: list[Step], verdict: str, kinds: list[str]) -> None:
    got = judged(ESCALATE, *steps)
    assert (got[0], got[2]) == (verdict, kinds)


def test_an_unknown_condition_is_refused() -> None:
    with pytest.raises(TypeError):
        DecisionVsShould(decision="escalate", when=[{"moon_phase": "full"}])


# ------------------------------------------------------------------ consistency
FACTS = Consistency(facts={"claim_id": r"CLM-\d{6}", "amount": r"₹\s?[\d,]+"})
CLAIM = {"id": "CLM-010003", "status": "approved", "approved_amount": 12400}
CONSISTENT = [
    (
        "both from the system",
        [call("get_claim"), ok("get_claim", CLAIM), say("CLM-010003 is approved for ₹12,400.")],
        "pass",
    ),
    (
        "invented amount",
        [call("get_claim"), ok("get_claim", CLAIM), say("CLM-010003 is approved for ₹40,000.")],
        "fail",
    ),
    (
        "invented claim id",
        [call("get_claim"), ok("get_claim", CLAIM), say("CLM-099999 is approved.")],
        "fail",
    ),
    (
        "said before it was looked up",
        [say("CLM-010003 is approved."), call("get_claim"), ok("get_claim", CLAIM)],
        "fail",
    ),
    (
        "result as JSON text",
        [ok("get_claim", '{"id": "CLM-010003"}'), say("Found CLM-010003.")],
        "pass",
    ),
    ("no facts stated", [say("How can I help?")], "pass"),
]


@pytest.mark.parametrize(("name", "steps", "verdict"), CONSISTENT, ids=[r[0] for r in CONSISTENT])
def test_consistency(name: str, steps: list[Step], verdict: str) -> None:
    assert judged(FACTS, *steps)[0] == verdict


# ------------------------------------------------------------------ shared behaviour
@pytest.mark.parametrize("kind", sorted(PATTERNS))
def test_every_pattern_skips_a_request_without_a_session(kind: str) -> None:
    pattern = {
        "argument_limit": REFUND,
        "claim_needs_action": PROMISE,
        "consistency": FACTS,
        "decision_vs_should": ESCALATE,
        "requires_before": CANCEL,
    }[kind]
    assert pattern.kind == kind
    assert pattern.evaluate(EvalRequest()).verdict == "skip"


def test_a_violation_says_what_and_the_raw_answer_says_where() -> None:
    result = CANCEL.evaluate(
        EvalRequest(session=Session("s9", (call("cancel_order", order_id=7),)))
    )
    assert (
        result.findings[0].label
        == "cancel_order without an earlier get_order for the same order_id"
    )
    assert result.raw["findings"][0]["step"] == 0 and result.raw["session"] == "s9"
    assert (result.provider, result.cost) == ("ours", 0.0)


# ------------------------------------------------------------------ from OpenAI messages
def test_a_session_from_openai_messages() -> None:
    session = Session.from_messages(
        "s1",
        [
            {"role": "user", "content": "Cancel order 7"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "get_order", "arguments": '{"order_id": 7}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "get_order", "content": '{"id": 7}'},
            {"role": "assistant", "content": "Order 7 is cancelled."},
        ],
    )
    assert [s.kind for s in session.steps] == ["user", "tool_call", "tool_result", "assistant"]
    assert session.steps[1].arguments == {"order_id": 7} and session.steps[2].result == {"id": 7}
    assert session.succeeded(1)


# ------------------------------------------------------------------ YAML and presets
def test_patterns_are_built_from_yaml_like_any_check() -> None:
    built = build(
        {
            "evaluators": {
                "cancel_needs_lookup": {
                    "adapter": "requires_before",
                    "action": "cancel_order",
                    "before": "get_order",
                },
                "refund_limit": {
                    "adapter": "argument_limit",
                    "tool": "issue_refund",
                    "field": "amount",
                    "max": 5000,
                },
            }
        }
    )
    assert judged(built["refund_limit"], call("issue_refund", amount=9000))[0] == "fail"
    assert built["cancel_needs_lookup"].name == "cancel_needs_lookup"


PRESET = [
    ("the preset alone needs a judge", {"preset": "customer-support"}, "needs a judge"),
    ("unknown preset", {"preset": "nope"}, "unknown preset 'nope'; known: customer-support"),
    (
        "a pattern missing its fields",
        {"evaluators": {"x": {"adapter": "requires_before"}}},
        "'x' (requires_before)",
    ),
]


@pytest.mark.parametrize(("name", "config", "says"), PRESET, ids=[r[0] for r in PRESET])
def test_refused(name: str, config: dict[str, Any], says: str) -> None:
    with pytest.raises(ConfigRefused) as refused:
        build(config)
    assert says in str(refused.value)


def test_a_team_overrides_removes_and_adds_on_top_of_a_preset() -> None:
    merged = with_preset(
        {
            "preset": "customer-support",
            "judge": JUDGE,
            "evaluators": {
                "pii": {"severity": {"URL": 0.0}},
                "groundedness": None,
                "refund_limit": {
                    "adapter": "argument_limit",
                    "tool": "issue_refund",
                    "field": "amount",
                    "max": 5000,
                },
            },
        }
    )
    assert merged["evaluators"]["pii"] == {"adapter": "presidio_pii", "severity": {"URL": 0.0}}
    assert "groundedness" not in merged["evaluators"]
    built = build({**merged})
    assert set(built) == {"pii", "refund_limit"} and built["pii"].severity["URL"] == 0.0  # type: ignore[attr-defined]


def test_the_preset_with_a_judge_builds() -> None:
    assert set(build({"preset": "customer-support", "judge": JUDGE})) == {"pii", "groundedness"}


def test_the_fnol_example_builds_and_catches_an_unbacked_payout_promise() -> None:
    from pathlib import Path

    from evalharness.config import load

    built = load(Path(__file__).parents[1] / "examples" / "claims-fnol.yaml")
    assert set(built) == {
        "pii",
        "groundedness",
        "payout_needs_claim_lookup",
        "payout_limit",
        "payout_promise_kept",
        "escalation",
        "facts_from_systems",
    }
    session = (call("get_claim", claim_id="CLM-010003"), say("Your payout is on its way."))
    verdicts = {
        name: check.evaluate(EvalRequest(session=Session("s", session))).verdict
        for name, check in built.items()
        if check.needs == {"session"}
    }
    assert verdicts == {
        "payout_needs_claim_lookup": "pass",
        "payout_limit": "pass",
        "payout_promise_kept": "fail",
        "escalation": "pass",
        "facts_from_systems": "pass",
    }
