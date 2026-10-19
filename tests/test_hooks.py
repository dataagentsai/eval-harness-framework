"""Hooks for your own loop: moments, matchers, decisions."""

from __future__ import annotations

from typing import Any

import pytest

from evalharness import Session, Step
from evalharness.hooks import Decision, Event, Hooks, check
from evalharness.patterns import RequiresBefore


def build() -> tuple[Hooks, list[str]]:
    """Hooks that record which of them ran."""
    hooks, ran = Hooks(), []

    def seen(name: str, decision: Decision | None = None) -> Any:
        def hook(event: Event) -> Decision | None:
            ran.append(name)
            return decision

        hook.__name__ = name
        return hook

    hooks.add("pre_tool", seen("refund_only"), tools=["issue_refund"])
    hooks.add("pre_tool", seen("issue_family"), tools=["issue_*"])
    hooks.add("pre_tool", seen("irreversible_kind"), side_effects=["irreversible"])
    hooks.add("pre_tool", seen("every_tool"))
    hooks.add("post_tool", seen("after_lookup"), tools=["get_order"])
    hooks.add("reply", seen("every_reply"))
    return hooks, ran


@pytest.mark.parametrize(
    ("event", "ran"),
    [
        (
            Event("pre_tool", tool="issue_refund", side_effect="irreversible"),
            ["refund_only", "issue_family", "irreversible_kind", "every_tool"],
        ),
        (
            Event("pre_tool", tool="issue_payout", side_effect="irreversible"),
            ["issue_family", "irreversible_kind", "every_tool"],
        ),
        (Event("pre_tool", tool="get_order", side_effect="read"), ["every_tool"]),
        (Event("post_tool", tool="get_order"), ["after_lookup"]),
        (Event("post_tool", tool="issue_refund"), []),
        (Event("reply", text="Done."), ["every_reply"]),
        (Event("pre_model", text="hi"), []),
    ],
)
def test_a_hook_runs_only_where_its_matcher_fits(event: Event, ran: list[str]) -> None:
    hooks, seen = build()
    assert hooks.run(event).action == "allow"
    assert seen == ran


@pytest.mark.parametrize(
    ("decisions", "action", "decided_by"),
    [
        ([None, None], "allow", ""),
        ([Decision("block", "no"), None], "block", "first"),
        ([None, Decision("escalate", "ask a person")], "escalate", "second"),
        ([Decision("modify", arguments={"amount": 10}), None], "modify", "first"),
        (
            [Decision("modify", arguments={"amount": 10}), Decision("block", "still no")],
            "block",
            "second",
        ),
    ],
)
def test_the_first_stop_wins_and_changes_are_handed_on(
    decisions: list[Decision | None], action: str, decided_by: str
) -> None:
    hooks = Hooks()
    for name, decision in zip(["first", "second"], decisions, strict=True):
        hooks.add("pre_tool", lambda e, d=decision: d, name=name)
    assert (
        hooks.run(Event("pre_tool", tool="t")).action,
        hooks.run(Event("pre_tool", tool="t")).hook,
    ) == (
        action,
        decided_by if action != "allow" else "",
    )


def test_a_later_hook_sees_the_changed_arguments() -> None:
    hooks, seen = Hooks(), []
    hooks.add("pre_tool", lambda e: Decision("modify", arguments={"amount": 100}))
    hooks.add("pre_tool", lambda e: seen.append(dict(e.arguments)))  # type: ignore[func-returns-value]
    decision = hooks.run(Event("pre_tool", tool="issue_refund", arguments={"amount": 99999}))
    assert seen == [{"amount": 100}] and decision.arguments == {"amount": 100}


def test_the_decorators_say_the_same_thing() -> None:
    hooks = Hooks()

    @hooks.before_tool("issue_refund")
    def cap(event: Event) -> Decision | None:
        return (
            Decision("block", "over the cap") if event.arguments.get("amount", 0) > 10000 else None
        )

    assert (
        hooks.run(Event("pre_tool", tool="issue_refund", arguments={"amount": 48000})).action
        == "block"
    )
    assert (
        hooks.run(Event("pre_tool", tool="issue_refund", arguments={"amount": 4999})).action
        == "allow"
    )
    assert (
        hooks.run(Event("pre_tool", tool="cancel_order", arguments={"amount": 48000})).action
        == "allow"
    )


@pytest.mark.parametrize(
    ("position", "tools", "error"),
    [("before_lunch", (), "unknown moment"), ("reply", ("issue_refund",), "no tool to match")],
)
def test_a_wrong_placement_is_refused(position: Any, tools: tuple[str, ...], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        Hooks().add(position, lambda e: None, tools=tools)


LOOKUP = RequiresBefore(
    name="refund_needs_lookup", action="issue_refund", before="get_order", same=["order_id"]
)


@pytest.mark.parametrize(
    ("so_far", "action"),
    [
        ((Step("user", text="refund 42"),), "block"),
        (
            (
                Step("user", text="refund 42"),
                Step("tool_call", name="get_order", arguments={"order_id": "42"}),
                Step("tool_result", name="get_order", result={"order_id": "42"}),
            ),
            "allow",
        ),
    ],
)
def test_a_session_check_stops_a_call_before_it_happens(
    so_far: tuple[Step, ...], action: str
) -> None:
    hooks = Hooks()
    hooks.add("pre_tool", check(LOOKUP), tools=["issue_refund"])
    event = Event(
        "pre_tool", tool="issue_refund", arguments={"order_id": "42"}, session=Session("s", so_far)
    )
    decision = hooks.run(event)
    assert decision.action == action
    if action == "block":
        assert (
            decision.hook == "refund_needs_lookup"
            and "without an earlier get_order" in decision.reason
        )


@pytest.mark.parametrize(
    ("mode_line", "mode", "applied"),
    [("", "shadow", "allow"), ("    mode: block\n", "block", "block")],
)
def test_a_rule_placed_in_yaml_starts_in_shadow(
    tmp_path: Any, mode_line: str, mode: str, applied: str
) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        "moments:\n  pre_tool: {budget_ms: 200, on_error: closed}\n"
        "evaluators:\n"
        "  refund_needs_lookup:\n"
        "    adapter: requires_before\n    action: issue_refund\n    before: get_order\n"
        "    at: pre_tool\n    tools: [issue_refund]\n"
        + mode_line
        + "  promise_kept:\n    adapter: claim_needs_action\n"
        "    claims: {refunded: {phrases: [refunded], tool: issue_refund}}\n"
    )
    from evalharness.config import load_hooks

    records: list[Any] = []
    hooks = load_hooks(path, on_record=records.append)
    assert [(p.name, p.position, p.mode) for p in hooks.placed] == [
        ("refund_needs_lookup", "pre_tool", mode)
    ]
    assert hooks.moment("pre_tool").budget_ms == 200
    event = Event("pre_tool", tool="issue_refund", session=Session("s", (Step("user", text="r"),)))
    assert hooks.run(event).action == applied
    (r,) = records
    assert (r.intended, r.applied, r.mode) == ("block", applied, mode)


@pytest.mark.parametrize(
    ("placement", "error"),
    [
        ("at: lunch", "at must be one of"),
        ("at: pre_tool\n    on_fail: shrug", "on_fail must be"),
        ("at: reply\n    tools: [issue_refund]", "tools is for pre_tool"),
        ("at: pre_tool\n    mode: loud", "mode must be one of"),
    ],
)
def test_a_wrong_yaml_placement_is_refused(tmp_path: Any, placement: str, error: str) -> None:
    from evalharness.config import ConfigRefused, load

    path = tmp_path / "rules.yaml"
    path.write_text(
        "evaluators:\n  r:\n    adapter: requires_before\n"
        f"    action: a\n    before: b\n    {placement}\n"
    )
    with pytest.raises(ConfigRefused, match=error):
        load(path)


# ------------------------------------------------------------- modes, errors, budgets
def _block(event: Event) -> Decision:
    return Decision("block", "no")


def _boom(event: Event) -> Decision:
    raise RuntimeError("the check broke")


@pytest.mark.parametrize(
    ("mode", "applied", "recorded"),
    [
        ("block", "block", ("block", "block")),
        ("alert", "allow", ("block", "allow")),
        ("shadow", "allow", ("block", "allow")),
        ("off", "allow", None),  # never runs, never recorded
    ],
)
def test_a_mode_decides_whether_a_decision_acts(
    mode: Any, applied: str, recorded: tuple[str, str] | None
) -> None:
    records: list[Any] = []
    hooks = Hooks(on_record=records.append)
    hooks.add("pre_tool", _block, mode=mode)
    assert hooks.run(Event("pre_tool", tool="t")).action == applied
    assert [(r.intended, r.applied) for r in records] == ([recorded] if recorded else [])


@pytest.mark.parametrize(
    ("on_error", "mode", "applied"),
    [("closed", "block", "block"), ("open", "block", "allow"), ("closed", "shadow", "allow")],
)
def test_a_broken_hook_fails_the_way_its_moment_says(
    on_error: Any, mode: Any, applied: str
) -> None:
    from evalharness.hooks import Moment

    records: list[Any] = []
    hooks = Hooks(moments={"pre_tool": Moment(on_error=on_error)}, on_record=records.append)
    hooks.add("pre_tool", _boom, mode=mode)
    decision = hooks.run(Event("pre_tool", tool="t"))
    assert decision.action == applied
    assert records[0].broke and records[0].intended == (
        "block" if on_error == "closed" else "allow"
    )
    if applied == "block":
        assert decision.reason == "hook broke: RuntimeError"


def test_a_check_too_slow_for_a_moment_is_refused_when_added() -> None:
    from evalharness.hooks import Moment

    hooks = Hooks(moments={"pre_tool": Moment(budget_ms=200)})
    with pytest.raises(ValueError, match="allows 200 ms. Run it online instead"):
        hooks.add("pre_tool", _block, name="groundedness", expected_ms=3000)
    hooks.add("pre_tool", _block, name="cap", expected_ms=5)  # fits


def test_a_run_over_budget_is_recorded() -> None:
    import time

    from evalharness.hooks import Moment

    def slow(event: Event) -> None:
        time.sleep(0.02)

    records: list[Any] = []
    hooks = Hooks(moments={"reply": Moment(budget_ms=1)}, on_record=records.append)
    hooks.add("reply", slow)
    hooks.run(Event("reply", text="hi"))
    assert records[0].over_budget and records[0].ms >= 1


def test_every_decision_goes_on_the_trace_without_its_reason() -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor

    from evalharness.sinks.otel_events import DECISION, decision_recorder

    exporter = InMemoryLogRecordExporter()
    logs = LoggerProvider()
    logs.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    hooks = Hooks(on_record=decision_recorder(logger_provider=logs, agent="shop"))
    hooks.add(
        "pre_tool",
        lambda e: Decision("block", "refund of ₹48,000 is over the cap"),
        name="refund_cap",
        mode="shadow",
    )
    hooks.run(Event("pre_tool", tool="issue_refund"))
    (emitted,) = exporter.get_finished_logs()
    a = dict(emitted.log_record.attributes or {})
    assert emitted.log_record.event_name == DECISION
    assert {
        k: a[k]
        for k in (
            "evalharness.rule",
            "evalharness.mode",
            "evalharness.intended",
            "evalharness.applied",
            "evalharness.tool",
            "evalharness.agent",
        )
    } == {
        "evalharness.rule": "refund_cap",
        "evalharness.mode": "shadow",
        "evalharness.intended": "block",
        "evalharness.applied": "allow",
        "evalharness.tool": "issue_refund",
        "evalharness.agent": "shop",
    }
    assert "₹" not in str(a)
