"""What each mapping does, offline: our shape into theirs, their answer into ours."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cases import CASES
from evalharness import Scale
from evalharness.adapter import Adapter
from evalharness.adapters.azure_groundedness import AzureGroundedness
from evalharness.adapters.deepeval_tools import DeepEvalToolCorrectness
from evalharness.adapters.presidio_pii import PresidioPii
from evalharness.adapters.ragas_faithfulness import RagasFaithfulness
from evalharness.judge_model import JudgeModel

FIXTURES = Path(__file__).parent / "fixtures"
GROQ = JudgeModel("openai/gpt-oss-120b", "http://judge.invalid", "NO_SUCH_KEY", 0.15, 0.75)


def fixture(kind: str, case: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{kind}__{case}.json").read_text())


# ------------------------------------------------------------- one scale, many units
SCALES = [
    ("azure 5 is best", Scale(1, 5, True, 3), 5, 1.0, "pass"),
    ("azure at threshold passes", Scale(1, 5, True, 3), 3, 0.5, "pass"),
    ("azure below threshold fails", Scale(1, 5, True, 3), 2, 0.25, "fail"),
    ("out of range is clamped", Scale(1, 5, True, 3), 9, 1.0, "pass"),
    ("harm 0 is best", Scale(0, 7, False, 2), 0, 1.0, "pass"),
    ("harm at threshold passes", Scale(0, 7, False, 2), 2, 5 / 7, "pass"),
    ("harm above threshold fails", Scale(0, 7, False, 2), 4, 3 / 7, "fail"),
    ("PII certain and severe", Scale(0, 1, False, 0.5), 1.0, 0.0, "fail"),
]


@pytest.mark.parametrize(
    ("name", "scale", "raw", "score", "verdict"), SCALES, ids=[s[0] for s in SCALES]
)
def test_every_provider_number_becomes_0_to_1_best_is_1(
    name: str, scale: Scale, raw: float, score: float, verdict: str
) -> None:
    assert scale.normalise(raw) == pytest.approx(score)
    assert scale.verdict(raw) == verdict


# ------------------------------------------------------------- our shape → theirs
def test_azure_gets_one_context_string_and_the_query() -> None:
    payload = AzureGroundedness().to_provider(CASES["grounded"])
    assert set(payload) == {"query", "response", "context"}
    assert payload["context"].count("\n\n") == 1  # two passages, ids gone


def test_ragas_gets_a_list_of_passages() -> None:
    payload = RagasFaithfulness().to_provider(CASES["grounded"])
    assert payload["retrieved_contexts"] == [p.text for p in CASES["grounded"].context or ()]


def test_deepeval_gets_calls_with_their_results_matched_by_name() -> None:
    case = DeepEvalToolCorrectness().to_provider(CASES["payout_called"])
    assert [t.name for t in case.tools_called] == ["get_claim", "issue_payout"]
    assert case.tools_called[0].output == {"id": "CLM-010003", "status": "approved"}
    assert case.tools_called[1].output is None  # no result recorded for it


# ------------------------------------------------------------- their answer → ours
RECORDED = [
    (AzureGroundedness, "grounded", "pass", 1.0, 0),
    (AzureGroundedness, "ungrounded", "fail", 0.25, 0),
    (RagasFaithfulness, "grounded", "pass", 1.0, 0),
    (RagasFaithfulness, "ungrounded", "fail", 0.0, 0),
    (DeepEvalToolCorrectness, "payout_called", "pass", 1.0, 0),
    (DeepEvalToolCorrectness, "payout_owed_not_called", "fail", 0.5, 1),
    (PresidioPii, "ungrounded", "pass", 1.0, 0),
    (PresidioPii, "pii_echo", "fail", pytest.approx(0.1), 5),
]


@pytest.mark.parametrize(
    ("cls", "case", "verdict", "score", "findings"),
    RECORDED,
    ids=[f"{c.kind}:{k}" for c, k, *_ in RECORDED],
)
def test_recorded_verdicts(
    cls: type[Adapter], case: str, verdict: str, score: float, findings: int
) -> None:
    result = cls(judge=GROQ).from_provider(fixture(cls.kind, case), CASES[case])
    assert (result.verdict, result.score, len(result.findings)) == (verdict, score, findings)


def test_the_missing_owed_action_is_named() -> None:
    result = DeepEvalToolCorrectness().from_provider(
        fixture("deepeval_tool_correctness", "payout_owed_not_called"),
        CASES["payout_owed_not_called"],
    )
    assert [(f.kind, f.label) for f in result.findings] == [("missing_tool", "issue_payout")]


# ------------------------------------------------------------- severity is policy
SEVERITY = [
    ("defaults: the email fails the reply", None, "fail"),
    (
        "emails and phones not severe here: only the name remains",
        {"EMAIL_ADDRESS": 0.1, "PHONE_NUMBER": 0.1, "PERSON": 0.4},
        "pass",
    ),
]


@pytest.mark.parametrize(("name", "severity", "verdict"), SEVERITY, ids=[s[0] for s in SEVERITY])
def test_severity_per_kind_is_configuration(
    name: str, severity: dict[str, float] | None, verdict: str
) -> None:
    result = PresidioPii(severity=severity).from_provider(
        fixture("presidio_pii", "pii_echo"), CASES["pii_echo"]
    )
    assert result.verdict == verdict


def test_a_confident_date_is_found_but_does_not_fail() -> None:
    result = PresidioPii().from_provider(fixture("presidio_pii", "pii_echo"), CASES["pii_echo"])
    date = next(f for f in result.findings if f.kind == "DATE_TIME")
    assert date.confidence > 0.8 and date.severity == 0.1
    text = CASES["pii_echo"].response.text  # type: ignore[union-attr]
    email = next(f for f in result.findings if f.kind == "EMAIL_ADDRESS")
    assert text[email.start : email.end] == "priya.sharma@example.com"


def test_azure_judge_tokens_become_cost_at_the_judges_price() -> None:
    raw = fixture("azure_groundedness", "ungrounded")
    tokens = raw["groundedness_properties"]
    expected = (tokens["prompt_tokens"] * 0.15 + tokens["completion_tokens"] * 0.75) / 1e6
    assert AzureGroundedness(judge=GROQ).from_provider(
        raw, CASES["ungrounded"]
    ).cost == pytest.approx(expected)
    assert AzureGroundedness().from_provider(raw, CASES["ungrounded"]).cost == 0.0


# ------------------------------------------------------------- what was lost, said
DROPPED = [
    (AzureGroundedness, "grounded", ("context.source_id: passages joined into one string",)),
    (PresidioPii, "grounded", ()),  # a PII check never wanted the query
    (DeepEvalToolCorrectness, "payout_owed_not_called", ("tool_definitions",)),
]


@pytest.mark.parametrize(
    ("cls", "case", "dropped"), DROPPED, ids=[f"{c.kind}:{k}" for c, k, _ in DROPPED]
)
def test_only_what_a_check_wanted_is_reported_dropped(
    cls: type[Adapter], case: str, dropped: tuple[str, ...]
) -> None:
    assert cls().dropped(CASES[case])[: len(dropped)] == dropped
    if not dropped:
        assert cls().dropped(CASES[case]) == ()
