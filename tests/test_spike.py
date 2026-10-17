"""The spike's claims, with no network: every mapper is a pure function, tested
against the provider answers recorded in `spike/fixtures/` by `spike.record`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agent_harness.evals import EvalRequest, Response

from spike.adapter import Adapter
from spike.adapters.azure_groundedness import AzureGroundedness, judge_cost
from spike.adapters.deepeval_tools import DeepEvalToolCorrectness
from spike.adapters.presidio_pii import PresidioPii
from spike.adapters.ragas_faithfulness import RagasFaithfulness
from spike.canonical import Scale
from spike.cases import CASES

FIXTURES = Path(__file__).parents[1] / "spike" / "fixtures"
AZURE, DEEPEVAL, RAGAS, PRESIDIO = (
    AzureGroundedness(),
    DeepEvalToolCorrectness(),
    RagasFaithfulness(),
    PresidioPii(),
)


def fixture(adapter: Adapter, case: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{adapter.name}__{case}.json").read_text())


# ------------------------------------------------------------- one scale, many units
ONE_TO_FIVE = Scale(1, 5, higher_is_better=True, threshold=3)
SEVERITY_0_7 = Scale(0, 7, higher_is_better=False, threshold=2)
CONFIDENCE = Scale(0, 1, higher_is_better=False, threshold=0.5)

SCALES = [
    ("azure 5 is best", ONE_TO_FIVE, 5, 1.0, "pass"),
    ("azure 1 is worst", ONE_TO_FIVE, 1, 0.0, "fail"),
    ("azure at threshold passes", ONE_TO_FIVE, 3, 0.5, "pass"),
    ("azure below threshold fails", ONE_TO_FIVE, 2, 0.25, "fail"),
    ("out of range is clamped", ONE_TO_FIVE, 9, 1.0, "pass"),
    ("harm 0 is best", SEVERITY_0_7, 0, 1.0, "pass"),
    ("harm at threshold passes", SEVERITY_0_7, 2, 5 / 7, "pass"),
    ("harm above threshold fails", SEVERITY_0_7, 4, 3 / 7, "fail"),
    ("no PII found", CONFIDENCE, 0.0, 1.0, "pass"),
    ("PII certain", CONFIDENCE, 1.0, 0.0, "fail"),
]


@pytest.mark.parametrize(("name", "scale", "raw", "score", "verdict"), SCALES, ids=[s[0] for s in SCALES])
def test_every_provider_number_becomes_0_to_1_best_is_1(
    name: str, scale: Scale, raw: float, score: float, verdict: str
) -> None:
    assert scale.normalise(raw) == pytest.approx(score)
    assert scale.verdict(raw) == verdict


# ------------------------------------------------------------- our shape → theirs
def test_azure_gets_one_context_string_and_the_query() -> None:
    payload = AZURE.to_provider(CASES["grounded"])
    assert set(payload) == {"query", "response", "context"}
    assert payload["context"].count("\n\n") == 1  # two passages, ids gone


def test_ragas_gets_a_list_of_passages() -> None:
    payload = RAGAS.to_provider(CASES["grounded"])
    assert payload["retrieved_contexts"] == [p.text for p in CASES["grounded"].context or ()]


def test_deepeval_gets_calls_with_their_results_matched_by_name() -> None:
    case = DEEPEVAL.to_provider(CASES["payout_called"])
    assert [t.name for t in case.tools_called] == ["get_claim", "issue_payout"]
    assert case.tools_called[0].output == {"id": "CLM-010003", "status": "approved"}
    assert case.tools_called[1].output is None  # no result recorded for it
    assert [t.name for t in case.expected_tools] == ["get_claim", "issue_payout"]


# ------------------------------------------------------------- their answer → ours
RECORDED = [
    (AZURE, "grounded", "pass", 1.0, 0),
    (AZURE, "ungrounded", "fail", 0.25, 0),
    (RAGAS, "grounded", "pass", 1.0, 0),
    (RAGAS, "ungrounded", "fail", 0.0, 0),
    (DEEPEVAL, "payout_called", "pass", 1.0, 0),
    (DEEPEVAL, "payout_owed_not_called", "fail", 0.5, 1),
    (PRESIDIO, "ungrounded", "pass", 1.0, 0),
    (PRESIDIO, "pii_echo", "fail", 0.0, 5),
]


@pytest.mark.parametrize(
    ("adapter", "case", "verdict", "score", "findings"),
    RECORDED,
    ids=[f"{a.name}:{c}" for a, c, *_ in RECORDED],
)
def test_a_recorded_answer_reads_back_as_one_result_shape(
    adapter: Adapter, case: str, verdict: str, score: float, findings: int
) -> None:
    raw = fixture(adapter, case)
    result = adapter.from_provider(raw, CASES[case])
    assert (result.verdict, result.findings.__len__()) == (verdict, findings)
    assert result.score == pytest.approx(score)
    assert result.raw == raw
    assert (result.evaluator, result.provider) == (adapter.name, adapter.provider)


def test_the_missing_owed_action_is_named() -> None:
    result = DEEPEVAL.from_provider(fixture(DEEPEVAL, "payout_owed_not_called"), CASES["payout_owed_not_called"])
    assert [(f.kind, f.label) for f in result.findings] == [("missing_tool", "issue_payout")]


def test_presidio_findings_keep_where_they_are_in_the_text() -> None:
    result = PRESIDIO.from_provider(fixture(PRESIDIO, "pii_echo"), CASES["pii_echo"])
    text = CASES["pii_echo"].response.text  # type: ignore[union-attr]
    email = next(f for f in result.findings if f.kind == "EMAIL_ADDRESS")
    assert text[email.start : email.end] == "priya.sharma@example.com"
    assert email.severity is None  # confidence is the provider's; severity is policy's


def test_azure_judge_tokens_become_cost_from_the_harness_price_table() -> None:
    raw = fixture(AZURE, "ungrounded")
    assert 0 < judge_cost(raw["groundedness_properties"]) < 0.01
    assert judge_cost(None) == 0.0


# ------------------------------------------------------------- what was lost, said
DROPPED = [
    (AZURE, "grounded", ("context.source_id: passages joined into one string",)),
    (PRESIDIO, "grounded", ()),  # a PII check never wanted the query
    (DEEPEVAL, "payout_owed_not_called", ("tool_definitions",)),
]


@pytest.mark.parametrize(("adapter", "case", "dropped"), DROPPED, ids=[f"{a.name}:{c}" for a, c, _ in DROPPED])
def test_only_what_a_check_wanted_is_reported_dropped(
    adapter: Adapter, case: str, dropped: tuple[str, ...]
) -> None:
    assert adapter.dropped(CASES[case])[: len(dropped)] == dropped


# ------------------------------------------------------------- skip and error
def test_a_request_without_context_is_skipped_not_failed() -> None:
    result = AZURE.evaluate(EvalRequest(response=Response("hello")))
    assert (result.verdict, result.reason) == ("skip", "skip: missing context")


def test_an_adapter_that_breaks_is_error_never_pass() -> None:
    result = AZURE.evaluate(CASES["grounded"])  # no judge configured
    assert result.verdict == "error"
    assert result.score is None
