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


NEGATED = [
    ("nothing paid yet (FNOL's real reply)", "Nothing has been paid yet.", "pass"),
    (
        "neither paid yet (FNOL's real reply)",
        "Both are approved; neither has been refunded yet.",
        "pass",
    ),
    ("can't confirm", "I can't confirm your refund has been issued.", "pass"),
    ("a question", "Has your refund has been issued?", "pass"),
    (
        "negation in another sentence only",
        "Your refund has been issued. Nothing else is needed.",
        "fail",
    ),
    (
        "mixed sentence: a documented miss",
        "Your refund has been issued, not the replacement.",
        "pass",
    ),
]


@pytest.mark.parametrize(("name", "text", "verdict"), NEGATED, ids=[r[0] for r in NEGATED])
def test_a_negated_or_questioned_sentence_is_not_a_claim(
    name: str, text: str, verdict: str
) -> None:
    assert judged(PROMISE, say(text))[0] == verdict


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


APPROVAL = DecisionVsShould(
    decision="awaiting_approval",
    when=[
        {
            "all": [
                {"tool_called": "request_payout"},
                {"result_of": "get_claim", "field": "approved_amount", "above": 25000},
            ]
        }
    ],
)
BIG, SMALL = {"id": "CLM-1", "approved_amount": 40000}, {"id": "CLM-2", "approved_amount": 9000}
APPROVALS = [
    (
        "over the limit, approval asked",
        [
            call("get_claim"),
            ok("get_claim", BIG),
            call("request_payout"),
            Step("decision", name="awaiting_approval"),
        ],
        "pass",
        [],
    ),
    (
        "over the limit, paid without approval",
        [call("get_claim"), ok("get_claim", BIG), call("request_payout"), call("issue_payout")],
        "fail",
        ["under"],
    ),
    (
        "within the limit, approval asked anyway",
        [
            call("get_claim"),
            ok("get_claim", SMALL),
            call("request_payout"),
            Step("decision", name="awaiting_approval"),
        ],
        "fail",
        ["over"],
    ),
    ("over the limit but no payout asked", [call("get_claim"), ok("get_claim", BIG)], "pass", []),
    (
        "the lookup failed: no amount known",
        [
            call("get_claim"),
            Step("tool_result", name="get_claim", result=BIG, is_error=True),
            call("request_payout"),
        ],
        "pass",
        [],
    ),
]


@pytest.mark.parametrize(
    ("name", "steps", "verdict", "kinds"), APPROVALS, ids=[r[0] for r in APPROVALS]
)
def test_approval_exactly_when_a_payout_is_over_the_limit(
    name: str, steps: list[Step], verdict: str, kinds: list[str]
) -> None:
    got = judged(APPROVAL, *steps)
    assert (got[0], got[2]) == (verdict, kinds)


HANDOVER = DecisionVsShould(
    decision="awaiting_human",
    when=[{"consecutive_failed_at_least": 2}, {"user_says": ["speak to a person"]}],
)
HANDED = Step("decision", name="awaiting_human")
WINDOWS = [
    ("two in a row, handed over", [failed("get_order"), failed("get_order"), HANDED], "pass", []),
    (
        "two in a row, not handed over",
        [failed("get_order"), failed("get_order")],
        "fail",
        ["under"],
    ),
    (
        "a success breaks the run",
        [failed("get_order"), ok("get_order"), failed("get_order")],
        "pass",
        [],
    ),
    # The clothing agent's own scenario: failures before a hand-back do not count.
    (
        "failures before a hand-back do not count",
        [failed("get_order"), failed("get_order"), HANDED, failed("get_order")],
        "pass",
        [],
    ),
    (
        "handed over twice, each for a reason",
        [failed("a"), failed("b"), HANDED, user("Let me speak to a person"), HANDED],
        "pass",
        [],
    ),
    (
        "the second hand-over had no reason",
        [failed("a"), failed("b"), HANDED, user("thanks"), HANDED],
        "fail",
        ["over"],
    ),
]


@pytest.mark.parametrize(
    ("name", "steps", "verdict", "kinds"), WINDOWS, ids=[r[0] for r in WINDOWS]
)
def test_a_decision_is_judged_in_its_own_window(
    name: str, steps: list[Step], verdict: str, kinds: list[str]
) -> None:
    got = judged(HANDOVER, *steps)
    assert (got[0], got[2]) == (verdict, kinds)


INJURY = DecisionVsShould(
    decision="awaiting_human", when=[{"user_says": ["was hurt"]}], check="under"
)
REPORTS = [
    ("an injury reported", "My passenger was hurt in the crash.", "fail"),
    (
        "FNOL's real words: nobody was hurt",
        "The car is a write-off. Nobody was hurt but the boot is crushed.",
        "pass",
    ),
    ("no one was hurt", "No one was hurt.", "pass"),
    ("a question", "What if someone was hurt?", "pass"),
]


@pytest.mark.parametrize(("name", "text", "verdict"), REPORTS, ids=[r[0] for r in REPORTS])
def test_what_the_customer_says_is_read_with_the_same_negation_guard(
    name: str, text: str, verdict: str
) -> None:
    assert judged(INJURY, user(text))[0] == verdict


def test_with_only_some_triggers_listed_only_under_is_judged() -> None:
    under_only = DecisionVsShould(
        decision="awaiting_human", when=[{"consecutive_failed_at_least": 2}], check="under"
    )
    assert (
        judged(under_only, user("thanks"), HANDED)[0] == "pass"
    )  # handed over for a reason not listed
    assert judged(under_only, failed("a"), failed("b"))[0] == "fail"
    with pytest.raises(TypeError):
        DecisionVsShould(decision="x", when=[], check="sideways")


OWED = DecisionVsShould(
    decision="awaiting_approval",
    when=[
        {
            "all": [
                {"tool_called": "request_refund"},
                {"result_of": "get_order", "field": "total", "above": 10000},
            ]
        },
        {
            "all": [
                {"tool_called": "request_refund"},
                {"result_of": "get_order", "field": "status", "not_in": ["returned"]},
            ]
        },
    ],
)
APPROVED = Step("decision", name="awaiting_approval")
REFUNDS = [
    (
        "returned and small: the agent decides alone",
        {"status": "returned", "total": 4999},
        False,
        "pass",
    ),
    (
        "returned and small, yet sent to a person",
        {"status": "returned", "total": 4999},
        True,
        "fail",
    ),
    (
        "delivered, not returned: a person decides",
        {"status": "delivered", "total": 4999},
        True,
        "pass",
    ),
    ("delivered, decided alone", {"status": "delivered", "total": 4999}, False, "fail"),
    ("returned but large: a person decides", {"status": "returned", "total": 12000}, True, "pass"),
]


@pytest.mark.parametrize(
    ("name", "order", "asked", "verdict"), REFUNDS, ids=[r[0] for r in REFUNDS]
)
def test_the_clothing_agents_refund_authority(
    name: str, order: dict[str, Any], asked: bool, verdict: str
) -> None:
    steps = [call("request_refund"), call("get_order"), ok("get_order", order)] + (
        [APPROVED] if asked else []
    )
    assert judged(OWED, *steps)[0] == verdict


def test_an_unknown_condition_is_refused() -> None:
    with pytest.raises(TypeError):
        DecisionVsShould(decision="escalate", when=[{"moon_phase": "full"}])
    with pytest.raises(TypeError):
        DecisionVsShould(decision="escalate", when=[{"all": [{"moon_phase": "full"}]}])


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


def test_repeating_the_customers_own_claim_id_is_not_inventing_it() -> None:
    steps = [user("Where is my claim CLM-019001?"), say("I could not find CLM-019001.")]
    assert judged(FACTS, *steps)[0] == "pass"
    strict = Consistency(facts={"claim_id": r"CLM-\d{6}"}, from_user=False)
    assert judged(strict, *steps)[0] == "fail"


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
        "payout_approval",
        "payout_promise_kept",
        "handed_to_person",
        "facts_from_systems",
    }
    session = (call("get_claim", id="CLM-010003"), say("Your payout has been issued."))
    verdicts = {
        name: check.evaluate(EvalRequest(session=Session("s", session))).verdict
        for name, check in built.items()
        if check.needs == {"session"}
    }
    assert verdicts == {
        "payout_needs_claim_lookup": "pass",
        "payout_approval": "pass",
        "payout_promise_kept": "fail",
        "handed_to_person": "pass",
        "facts_from_systems": "pass",
    }
