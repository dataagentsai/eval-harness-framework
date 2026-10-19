"""The cost rules through llm-cost-explainer, as ordinary verdicts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from evalharness.costs import LlmCostExplainer, RuleRunner, results_of


def finding(rule: str, scope: dict[str, str], saving: float) -> dict[str, Any]:
    return {
        "rule_id": rule,
        "title": f"title {rule}",
        "scope": scope,
        "summary": f"summary {rule}",
        "savings_day": saving,
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"rules_run": ["LLM-01", "LLM-06"]}, {"LLM-01": "pass", "LLM-06": "pass"}),
        (
            {
                "rules_run": ["LLM-01", "LLM-06"],
                "findings": [finding("LLM-06", {"api_key_ref": "k1"}, 10.0)],
            },
            {"LLM-01": "pass", "LLM-06": "fail"},
        ),
        (  # a rule the export can't feed is "could not judge", never a pass
            {"rules_run": ["LLM-01"], "skipped": [("LLM-06", "Bulk", "export lacks hourly")]},
            {"LLM-01": "pass", "LLM-06": "skip"},
        ),
    ],
)
def test_each_rule_becomes_one_verdict(payload: dict[str, Any], expected: dict[str, str]) -> None:
    assert {r.evaluator: r.verdict for r in results_of(payload)} == expected


def test_a_failing_rule_carries_each_scope_and_the_saving() -> None:
    (r,) = results_of(
        {
            "rules_run": ["LLM-06"],
            "findings": [
                finding("LLM-06", {"api_key_ref": "k1"}, 10.0),
                finding("LLM-06", {"api_key_ref": "k2"}, 5.0),
            ],
        }
    )
    assert [f.label for f in r.findings] == [
        "api_key_ref=k1: $300/month",
        "api_key_ref=k2: $150/month",
    ]
    assert r.raw_score == 15.0 and r.reason.startswith("2 findings, about $450/month to save")
    assert r.provider == "llm-cost-explainer"


lce = pytest.importorskip("lce.synth")

SCENARIOS = [  # llm-cost-explainer's own scenarios, and the rules each must trip
    ("clean", set()),
    ("bulk_realtime", {"LLM-06", "LLM-01"}),
    ("priority_background", {"LLM-22", "LLM-01"}),
    ("deprecated_model", {"LLM-24"}),
    ("short_cache", {"LLM-26"}),
]


@pytest.mark.parametrize(("scenario", "failing"), SCENARIOS)
def test_the_runner_on_known_bad_days(scenario: str, failing: set[str], tmp_path: Path) -> None:
    runner = LlmCostExplainer(lce.generate(tmp_path, scenario))
    assert isinstance(runner, RuleRunner)
    results = runner.run()
    assert {r.evaluator for r in results if r.verdict == "fail"} == failing
    assert len(results) == 6  # the six rules llm-cost-explainer has built
