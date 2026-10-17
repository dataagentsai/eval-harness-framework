"""`evaluators.yaml`: what it builds, what it refuses, and that a threshold is YAML only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cases import CASES
from evalharness.config import ConfigRefused, build, load

EXAMPLE = Path(__file__).parents[1] / "evaluators.example.yaml"
JUDGE = {"model": "m", "base_url": "http://judge.invalid", "api_key_env": "NO_SUCH_KEY"}


def test_the_example_builds_every_evaluator_by_its_configured_name() -> None:
    built = load(EXAMPLE)
    assert set(built) == {"groundedness", "faithfulness", "tools_called", "pii"}
    assert built["groundedness"].kind == "azure_groundedness"
    assert all(a.name == n for n, a in built.items())


REFUSED: list[tuple[str, dict[str, Any], str]] = [
    ("unknown adapter", {"evaluators": {"x": {"adapter": "nope"}}}, "unknown adapter 'nope'"),
    ("unknown top-level field", {"judges": {}}, "unknown field(s) judges"),
    (
        "unknown adapter field",
        {"evaluators": {"pii": {"adapter": "presidio_pii", "colour": 1}}},
        "'pii' (presidio_pii)",
    ),
    (
        "judged check, no judge",
        {"evaluators": {"g": {"adapter": "azure_groundedness"}}},
        "needs a judge",
    ),
    ("unknown judge field", {"judge": {**JUDGE, "temp": 0}}, "judge:"),
    (
        "unknown scale field",
        {
            "judge": JUDGE,
            "evaluators": {"g": {"adapter": "azure_groundedness", "scale": {"min": 1}}},
        },
        "g.scale: unknown",
    ),
    (
        "empty scale",
        {
            "judge": JUDGE,
            "evaluators": {
                "g": {
                    "adapter": "azure_groundedness",
                    "scale": {"raw_min": 5, "raw_max": 1, "higher_is_better": True, "threshold": 3},
                }
            },
        },
        "raw_max must be above",
    ),
]


@pytest.mark.parametrize(("name", "config", "says"), REFUSED, ids=[r[0] for r in REFUSED])
def test_startup_refuses(name: str, config: dict[str, Any], says: str) -> None:
    with pytest.raises(ConfigRefused, match=None) as refused:
        build(config)
    assert says in str(refused.value)


def test_raising_a_threshold_is_a_yaml_change_only() -> None:
    raw = {"groundedness": 4.0, "groundedness_reason": "", "groundedness_result": "pass"}

    def verdict(threshold: float) -> str:
        scale = {"raw_min": 1, "raw_max": 5, "higher_is_better": True, "threshold": threshold}
        built = build(
            {"judge": JUDGE, "evaluators": {"g": {"adapter": "azure_groundedness", "scale": scale}}}
        )
        return built["g"].from_provider(raw, CASES["grounded"]).verdict

    assert (verdict(3), verdict(5)) == ("pass", "fail")
