"""Rules linked to requirements and to the standard's obligations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from evalharness.config import KINDS, adapter_class, load
from evalharness.requirements import requirement

SPEC: dict[str, Any] = {
    "operations": {"issue_payout": {"authority": {"agent_when": "approved_amount <= 25000"}}},
    "policies": {
        "P-PAYOUT": {"rule": "an amount above ₹25,000 needs a claims handler"},
        "approval": {"statements": [{"id": "P-APPROVAL-FINAL", "rule": "a decision is final"}]},
        "escalation": {
            "on_request": [{"id": "injury-reported", "when": "someone was hurt"}],
            "on_condition": [
                {"id": "tool-unavailable", "when": {"field": "consecutive_failed", "at_least": 2}}
            ],
        },
        "personal_data_in_conversation": ["bank account numbers typed into the chat"],
    },
}


@pytest.mark.parametrize(
    ("rid", "expected"),
    [
        ("P-PAYOUT", "an amount above ₹25,000 needs a claims handler"),
        ("P-APPROVAL-FINAL", "a decision is final"),
        ("escalation.injury-reported", "hand over to a person when someone was hurt"),
        (
            "escalation.tool-unavailable",
            'hand over to a person when {"field": "consecutive_failed", "at_least": 2}',
        ),
        ("issue_payout.authority.agent_when", "approved_amount <= 25000"),
        ("personal_data_in_conversation", "bank account numbers typed into the chat"),
        ("P-NOPE", None),
        ("escalation.nope", None),
        ("issue_payout.nope", None),
        ("no_such_operation.authority", None),
    ],
)
def test_a_requirement_is_found_in_the_spec(rid: str, expected: str | None) -> None:
    assert requirement(SPEC, rid) == expected


ROOT = Path(__file__).parents[1]
SPECS = Path.home() / "clean-ai-engineering" / "drafts" / "examples"


@pytest.mark.parametrize("example", ["claims-fnol.yaml", "support-agent-clothing.yaml"])
def test_every_requirement_an_example_names_is_in_its_spec(example: str) -> None:
    config = yaml.safe_load((ROOT / "examples" / example).read_text())
    spec_path = SPECS / Path(config["spec"]).name
    if not spec_path.is_file():
        pytest.skip(f"{spec_path} is not on this machine")
    spec = yaml.safe_load(spec_path.read_text())
    named = [
        rid for check in load(ROOT / "examples" / example).values() for rid in check.requirements
    ]
    assert named
    assert [rid for rid in named if requirement(spec, rid) is None] == []


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_every_obligation_a_check_declares_is_a_catalog_id(kind: str) -> None:
    for oid in adapter_class(kind).obligations:
        assert oid.startswith("AAC-") and len(oid) == 8 and oid[4:].isdigit(), oid
