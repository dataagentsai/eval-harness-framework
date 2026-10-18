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


def test_a_rule_placed_in_yaml_becomes_a_hook(tmp_path: Any) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        """
evaluators:
  refund_needs_lookup:
    adapter: requires_before
    action: issue_refund
    before: get_order
    at: pre_tool
    tools: [issue_refund]
    on_fail: block
  promise_kept:
    adapter: claim_needs_action
    claims: {refunded: {phrases: ["has been refunded"], tool: issue_refund}}
"""
    )
    from evalharness.config import load_hooks

    hooks = load_hooks(path)
    assert [(p.name, p.position, p.match.tools) for p in hooks.placed] == [
        ("refund_needs_lookup", "pre_tool", ("issue_refund",))
    ]
    event = Event(
        "pre_tool", tool="issue_refund", session=Session("s", (Step("user", text="refund"),))
    )
    assert hooks.run(event).action == "block"


@pytest.mark.parametrize(
    ("placement", "error"),
    [
        ("at: lunch", "at must be one of"),
        ("at: pre_tool\n    on_fail: shrug", "on_fail must be"),
        ("at: reply\n    tools: [issue_refund]", "tools is for pre_tool"),
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
