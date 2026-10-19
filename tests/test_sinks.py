"""Verdicts as OpenTelemetry gen_ai.evaluation.result events."""

from __future__ import annotations

from typing import Any

import pytest

from evalharness import EvalRequest, EvalResult, Finding, Session, Step
from evalharness.patterns import Consistency
from evalharness.sinks import ResultSink

pytest.importorskip("opentelemetry.sdk")

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk._logs import LoggerProvider  # noqa: E402
from opentelemetry.sdk._logs.export import (  # noqa: E402
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402

from evalharness.sinks.otel_events import EVENT, OtelEvents, attributes  # noqa: E402

FACTS = Consistency(
    name="facts_from_systems", facts={"amount": r"₹\s?[\d,]+"}, requirements=["P-CLAIM-STATUS"]
)
INVENTED = Session(
    "conv-9",
    (
        Step("user", text="How much?"),
        Step("tool_call", name="get_claim"),
        Step("tool_result", name="get_claim", result={"approved_amount": 12400}),
        Step("assistant", text="You will get ₹15,000."),
    ),
)


def result_of(session: Session) -> tuple[EvalResult, EvalRequest]:
    request = EvalRequest(session=session)
    return FACTS.evaluate(request), request


def vendor(reason: str, verdict: str = "fail") -> EvalResult:
    return EvalResult(
        verdict,
        0.2,
        2.0,
        0.5,
        reason,
        "groundedness",
        "1",
        "azure",  # type: ignore[arg-type]
        findings=(Finding("ungrounded", 0.9),),
    )


@pytest.mark.parametrize(
    ("make", "explain", "expected"),
    [
        # our check, content-free: counts and kinds, never the quoted amount
        (
            lambda: result_of(INVENTED),
            "counts",
            {
                "gen_ai.evaluation.name": "facts_from_systems",
                "gen_ai.evaluation.score.label": "fail",
                "gen_ai.evaluation.explanation": "0 of 1 held; unsupported_fact",
                "evalharness.finding_kinds": "unsupported_fact",
                "evalharness.requirements": "P-CLAIM-STATUS",
                "evalharness.obligations": "AAC-0029",
                "evalharness.session.id": "conv-9",
            },
        ),
        # the same, where the store may hold content: the full reason
        (
            lambda: result_of(INVENTED),
            "full",
            {
                "gen_ai.evaluation.explanation": "0 of 1 held; "
                "amount “₹15,000” is in no earlier tool result",
            },
        ),
        # an outside provider's reason is a model's words: left out
        (
            lambda: (vendor("The reply claims the claim was paid on 3 May."), None),
            "counts",
            {
                "gen_ai.evaluation.explanation": "fail; ungrounded",
                "evalharness.provider": "azure",
                "evalharness.raw_score": 2.0,
                "evalharness.threshold": 0.5,
            },
        ),
        (lambda: (vendor("boom", verdict="error"), None), "counts", {"error.type": "_OTHER"}),
    ],
)
def test_the_event_carries_the_conventions_names_and_no_content(
    make: Any, explain: str, expected: dict[str, Any]
) -> None:
    result, request = make()
    got = attributes(result, rule=FACTS if request else None, request=request, explain=explain)
    assert {k: got.get(k) for k in expected} == expected
    if explain == "counts":
        assert "₹" not in str(got) and "3 May" not in str(got)


def test_an_event_is_emitted_on_the_judged_turns_trace() -> None:
    exporter = InMemoryLogRecordExporter()
    logs = LoggerProvider()
    logs.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    sink = OtelEvents(logger_provider=logs, synthetic=True)
    assert isinstance(sink, ResultSink)
    tracer = TracerProvider().get_tracer("test")
    result, request = result_of(INVENTED)
    with tracer.start_as_current_span("agent.turn") as span:
        sink.record(result, rule=FACTS, request=request)
        turn = span.get_span_context()
    (emitted,) = exporter.get_finished_logs()
    record = emitted.log_record
    assert record.event_name == EVENT
    assert (record.trace_id, record.span_id) == (turn.trace_id, turn.span_id)
    assert record.attributes is not None and record.attributes["evalharness.synthetic"] is True
    assert trace.get_current_span() is trace.INVALID_SPAN


NOTHING_HERE = Session("conv-1", (Step("user", text="hi"), Step("assistant", text="Hello.")))


@pytest.mark.parametrize(
    ("session", "label"),
    [(INVENTED, "fail"), (NOTHING_HERE, "not_applicable")],
)
def test_nothing_to_check_is_not_a_pass(session: Session, label: str) -> None:
    result, request = result_of(session)
    got = attributes(result, rule=FACTS, request=request)
    assert got["gen_ai.evaluation.score.label"] == label
    assert got["evalharness.verdict"] == result.verdict
