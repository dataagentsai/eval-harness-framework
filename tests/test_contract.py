"""The contract every adapter must pass, as one table over the registry.

A new adapter is added to `ADAPTERS` and to `RECORDED` below; nothing else in
this file changes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args

import pytest

from cases import CASES
from evalharness import NEEDS, EvalRequest, Evaluator, Response, Speed
from evalharness.adapter import Adapter, Stability
from evalharness.adapters import ADAPTERS
from evalharness.config import adapter_class
from evalharness.judge_model import JudgeModel

FIXTURES = Path(__file__).parent / "fixtures"
JUDGE = JudgeModel("m", "http://judge.invalid", "NO_SUCH_KEY", 1.0, 2.0)
CLASSES = [adapter_class(kind) for kind in sorted(ADAPTERS)]
ids = [c.kind for c in CLASSES]

RECORDED: Mapping[str, tuple[str, ...]] = {
    "azure_groundedness": ("grounded", "ungrounded"),
    "deepeval_tool_correctness": ("payout_called", "payout_owed_not_called"),
    "presidio_pii": ("grounded", "ungrounded", "payout_called", "pii_echo"),
    "ragas_faithfulness": ("grounded", "ungrounded"),
}


def fixture(kind: str, case: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{kind}__{case}.json").read_text())


def test_every_registered_adapter_has_recorded_answers() -> None:
    assert set(RECORDED) == set(ADAPTERS)


@pytest.mark.parametrize("cls", CLASSES, ids=ids)
def test_declares_itself_in_the_shared_vocabulary(cls: type[Adapter]) -> None:
    assert cls.needs <= set(NEEDS) and cls.carries <= set(NEEDS)
    assert cls.needs <= cls.carries
    assert cls.wants is None or cls.carries <= cls.wants <= set(NEEDS)
    assert cls.speed in get_args(Speed) and cls.stability in get_args(Stability)
    assert cls.default_scale.raw_max > cls.default_scale.raw_min
    assert ADAPTERS[cls.kind].endswith(f":{cls.__name__}")


@pytest.mark.parametrize("cls", CLASSES, ids=ids)
def test_is_the_port(cls: type[Adapter]) -> None:
    assert isinstance(cls(judge=JUDGE), Evaluator)


@pytest.mark.parametrize("cls", CLASSES, ids=ids)
def test_a_request_missing_what_it_needs_is_skipped(cls: type[Adapter]) -> None:
    result = cls(judge=JUDGE).evaluate(EvalRequest(meta=CASES["grounded"].meta))
    assert result.verdict == "skip" and result.score is None
    assert result.reason.startswith("skip: missing ")


@pytest.mark.parametrize("cls", CLASSES, ids=ids)
def test_a_provider_that_breaks_is_error_never_pass(
    cls: type[Adapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: Adapter, payload: Any) -> Mapping[str, Any]:
        raise ConnectionError("provider down")

    monkeypatch.setattr(cls, "call", broken)
    case = CASES[RECORDED[cls.kind][0]]
    result = cls(judge=JUDGE).evaluate(case)
    assert (result.verdict, result.score) == ("error", None)
    assert "provider down" in result.reason


@pytest.mark.parametrize(
    ("kind", "case"),
    [(k, c) for k, cs in RECORDED.items() for c in cs],
    ids=[f"{k}:{c}" for k, cs in RECORDED.items() for c in cs],
)
def test_a_recorded_answer_reads_back_as_one_result_shape(kind: str, case: str) -> None:
    adapter = adapter_class(kind)(name="configured", judge=JUDGE)
    raw = fixture(kind, case)
    result = adapter.from_provider(raw, CASES[case])
    assert result.verdict in ("pass", "fail")
    assert result.score is not None and 0.0 <= result.score <= 1.0
    assert result.threshold == adapter.scale.normalised_threshold
    assert (result.evaluator, result.provider) == ("configured", adapter.provider)
    assert result.raw == raw


def test_a_response_without_tools_recorded_is_not_a_response_with_none() -> None:
    unrecorded = EvalRequest(response=Response("hi")).provides()
    none_made = EvalRequest(response=Response("hi", tool_calls=())).provides()
    assert "tool_calls" not in unrecorded and "tool_calls" in none_made
