"""Who may change a rule, and when a rule may block."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from evalharness.config import ConfigRefused, build, changes, layered, load

ORG = {
    "evaluators": {
        "pii": {"adapter": "presidio_pii", "locked": True, "owner": "risk-office"},
        "refund_cap": {
            "adapter": "argument_limit",
            "tool": "issue_refund",
            "field": "amount",
            "max": 10000,
        },
    }
}


def agent(evaluators: dict[str, Any]) -> dict[str, Any]:
    return {"evaluators": evaluators}


@pytest.mark.parametrize(
    ("evaluators", "refused"),
    [
        ({"pii": None}, "pii is locked by the organisation's policy; only its owner (risk-office)"),
        ({"pii": {"locked": False}}, "pii is locked"),
        ({"pii": {"adapter": "presidio_pii"}}, None),  # repeating it unchanged is allowed
        ({"refund_cap": {"max": 20000}}, None),  # an unlocked rule may be changed
        ({"refund_cap": None}, None),  # or removed (T22)
    ],
)
def test_a_locked_rule_cant_be_changed_by_the_agent(
    evaluators: dict[str, Any], refused: str | None
) -> None:
    if refused:
        with pytest.raises(ConfigRefused, match=re.escape(refused)):
            layered(agent(evaluators), ORG)
    else:
        layered(agent(evaluators), ORG)


def test_every_change_to_an_inherited_rule_is_listed() -> None:
    merged, found = layered(
        agent(
            {
                "refund_cap": {"max": 20000},
                "pii": {"adapter": "presidio_pii"},
                "lookup_first": {"adapter": "requires_before", "action": "a", "before": "b"},
            }
        ),
        ORG,
    )
    assert [(c.rule, c.field, c.before, c.after) for c in found] == [
        ("refund_cap", "max", 10000, 20000),
        (
            "lookup_first",
            "(added)",
            None,
            {"adapter": "requires_before", "action": "a", "before": "b"},
        ),
    ]
    assert merged["evaluators"]["refund_cap"]["max"] == 20000
    _, removed = layered(agent({"refund_cap": None}), ORG)
    assert [(c.rule, c.field) for c in removed] == [("refund_cap", "(removed)")]


PLACED = {
    "adapter": "argument_limit",
    "tool": "issue_refund",
    "field": "amount",
    "max": 10000,
    "at": "pre_tool",
}


@pytest.mark.parametrize(
    ("extra", "refused"),
    [
        ({"mode": "shadow"}, None),
        ({"mode": "block"}, "can't block without an owner"),
        ({"mode": "block", "owner": "ops"}, "can't block yet: give its evidence"),
        (
            {
                "mode": "block",
                "owner": "ops",
                "evidence": {"precision": 0.8, "sample": 200, "measured": "2026-10-19"},
            },
            "precision 0.8 on 200",
        ),
        (
            {
                "mode": "block",
                "owner": "ops",
                "evidence": {"precision": 0.99, "sample": 10, "measured": "2026-10-19"},
            },
            "on 10 conversations",
        ),
        (
            {
                "mode": "block",
                "owner": "ops",
                "evidence": {"precision": 0.95, "sample": 80, "measured": "2026-10-19"},
            },
            None,
        ),
        ({"mode": "block", "owner": "risk-office", "locked": True}, None),  # the risk owner's call
    ],
)
def test_a_rule_blocks_only_with_an_owner_and_evidence(
    extra: dict[str, Any], refused: str | None
) -> None:
    config = agent({"refund_cap": {**PLACED, **extra}})
    if refused:
        with pytest.raises(ConfigRefused, match=refused):
            build(config)
    else:
        built = build(config)["refund_cap"]
        assert built.governance.get("owner") == extra.get("owner")


def test_files_on_disk_are_layered_the_same(tmp_path: Path) -> None:
    org, mine = tmp_path / "org.yaml", tmp_path / "agent.yaml"
    org.write_text(yaml.safe_dump({**ORG, "moments": {"pre_tool": {"budget_ms": 200}}}))
    mine.write_text(yaml.safe_dump(agent({"refund_cap": {"max": 5000}})))
    assert load(mine, org=org)["refund_cap"].max == 5000  # type: ignore[attr-defined]
    assert [c.field for c in changes(mine, org=org)] == ["max"]
