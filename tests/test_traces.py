"""Traces in, sessions out: OTLP files and the GenAI conventions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalharness import EvalRequest
from evalharness.patterns import ClaimNeedsAction, RequiresBefore
from evalharness.traces import OtlpFile, Span, TraceSource, otlp_spans, sessions

# Pydantic AI's own instrumentation, recorded by scripts/record_genai_traces.py.
RECORDED = Path(__file__).parent / "fixtures" / "otlp" / "pydantic_ai_refunds.jsonl"


def shape(session_steps: Any) -> list[str]:
    """A session as short words: `user:…`, `call:name`, `ok:name`, `err:name`, `say:…`."""
    words = {"user": "user", "assistant": "say", "tool_call": "call"}
    out = []
    for s in session_steps:
        if s.kind == "tool_result":
            out.append(f"{'err' if s.is_error else 'ok'}:{s.name}")
        elif s.kind in ("user", "assistant"):
            out.append(f"{words[s.kind]}:{s.text}")
        else:
            out.append(f"{words[s.kind]}:{s.name}")
    return out


# ----------------------------------------------------------- recorded traces


@pytest.mark.parametrize(
    ("conversation", "expected", "turns"),
    [
        (
            "conv-lookup-first",
            [
                "user:Please refund order 42.",
                "call:get_order",
                "ok:get_order",
                "call:issue_refund",
                "ok:issue_refund",
                "say:Your refund of 500 for order 42 has been issued.",
                "user:Thanks!",
                "say:You're welcome.",
            ],
            2,
        ),
        (
            "conv-no-lookup",
            [
                "user:Refund order 42 now.",
                "call:issue_refund",
                "ok:issue_refund",
                "say:Done, your refund of 500 is on its way.",
            ],
            1,
        ),
        (
            "conv-tool-error",
            [
                "user:Where is my refund for order 99?",
                "call:get_order",
                "err:get_order",
                "say:I couldn't find order 99. Could you check the number?",
            ],
            1,
        ),
    ],
)
def test_recorded_conversations(conversation: str, expected: list[str], turns: int) -> None:
    rebuilt = {s.id: s for s in sessions(OtlpFile(RECORDED).spans())}
    session = rebuilt[conversation]
    assert shape(session.steps) == expected
    assert max(s.turn for s in session.steps) == turns


def test_recorded_calls_keep_ids_arguments_and_results() -> None:
    session = {s.id: s for s in sessions(OtlpFile(RECORDED).spans())}["conv-lookup-first"]
    ((_, refund),) = session.calls("issue_refund")
    assert (refund.call_id, refund.arguments) == ("call_a2", {"order_id": "42", "amount": 500})
    results = [s for s in session.steps if s.kind == "tool_result"]
    assert results[0].result == {"order_id": "42", "status": "returned", "total": 500}


def test_the_file_source_is_a_trace_source() -> None:
    assert isinstance(OtlpFile(RECORDED), TraceSource)


@pytest.mark.parametrize(
    ("pattern", "verdicts"),
    [
        (
            RequiresBefore(action="issue_refund", before="get_order", same=["order_id"]),
            {"conv-lookup-first": "pass", "conv-no-lookup": "fail", "conv-tool-error": "pass"},
        ),
        (
            ClaimNeedsAction(
                claims={"refunded": {"phrases": ["refund of 500"], "tool": "issue_refund"}}
            ),
            {"conv-lookup-first": "pass", "conv-no-lookup": "pass", "conv-tool-error": "pass"},
        ),
    ],
)
def test_patterns_on_a_third_party_agents_traces(pattern: Any, verdicts: dict[str, str]) -> None:
    got = {
        s.id: pattern.evaluate(EvalRequest(session=s)).verdict
        for s in sessions(OtlpFile(RECORDED).spans())
    }
    assert got == verdicts


# ------------------------------------------------------------ built by hand


def chat(trace: str, at: float, inputs: list[Any], outputs: list[Any], **attrs: Any) -> Span:
    return Span(
        trace_id=trace,
        span_id=f"c{at}",
        name="chat",
        start=at,
        end=at + 0.5,
        attributes={
            "gen_ai.operation.name": "chat",
            "gen_ai.input.messages": json.dumps(inputs),
            "gen_ai.output.messages": json.dumps(outputs),
            **attrs,
        },
    )


def tool(
    trace: str, at: float, name: str, cid: str, result: Any, error: bool = False, **attrs: Any
) -> Span:
    return Span(
        trace_id=trace,
        span_id=f"t{at}",
        name=f"execute_tool {name}",
        start=at,
        end=at + 0.1,
        error=error,
        attributes={
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": name,
            "gen_ai.tool.call.id": cid,
            "gen_ai.tool.call.arguments": "{}",
            "gen_ai.tool.call.result": json.dumps(result),
            **attrs,
        },
    )


def u(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"type": "text", "content": text}]}


def a(text: str) -> dict[str, Any]:
    return {"role": "assistant", "parts": [{"type": "text", "content": text}]}


def asks(name: str, cid: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "parts": [{"type": "tool_call", "id": cid, "name": name, "arguments": {}}],
    }


def answers(cid: str, response: Any) -> dict[str, Any]:
    return {
        "role": "tool",
        "parts": [{"type": "tool_call_response", "id": cid, "response": response}],
    }


@pytest.mark.parametrize(
    ("name", "spans", "expected"),
    [
        (
            # No conversation id: each trace is its own session.
            "trace_is_the_fallback",
            [chat("t1", 1, [u("hi")], [a("hello")]), chat("t2", 5, [u("bye")], [a("ciao")])],
            {"t1": ["user:hi", "say:hello"], "t2": ["user:bye", "say:ciao"]},
        ),
        (
            # session.id joins turns where gen_ai.conversation.id is absent.
            "session_id_joins_turns",
            [
                chat("t1", 1, [u("hi")], [a("hello")], **{"session.id": "s"}),
                chat("t2", 5, [u("hi"), a("hello"), u("bye")], [a("ciao")], **{"session.id": "s"}),
            ],
            {"s": ["user:hi", "say:hello", "user:bye", "say:ciao"]},
        ),
        (
            # An agent that resends no history: each turn's words are still new.
            "stateless_agent",
            [
                chat("t1", 1, [u("hi")], [a("hello")], **{"gen_ai.conversation.id": "c"}),
                chat("t2", 5, [u("bye")], [a("ciao")], **{"gen_ai.conversation.id": "c"}),
            ],
            {"c": ["user:hi", "say:hello", "user:bye", "say:ciao"]},
        ),
        (
            # No execute_tool spans: calls and results come from the messages.
            "messages_only",
            [
                chat("t1", 1, [u("order?")], [asks("get_order", "x1")]),
                chat(
                    "t1",
                    3,
                    [u("order?"), asks("get_order", "x1"), answers("x1", {"id": 7})],
                    [a("found")],
                ),
            ],
            {"t1": ["user:order?", "call:get_order", "ok:get_order", "say:found"]},
        ),
        (
            # Both recorded: each call and result appears once.
            "messages_and_tool_spans",
            [
                chat("t1", 1, [u("order?")], [asks("get_order", "x1")]),
                tool("t1", 2, "get_order", "x1", {"id": 7}),
                chat(
                    "t1",
                    3,
                    [u("order?"), asks("get_order", "x1"), answers("x1", {"id": 7})],
                    [a("found")],
                ),
            ],
            {"t1": ["user:order?", "call:get_order", "ok:get_order", "say:found"]},
        ),
        (
            "tool_error_status",
            [tool("t1", 1, "get_order", "x1", "boom", error=True)],
            {"t1": ["call:get_order", "err:get_order"]},
        ),
        (
            # Spans that are neither chat nor execute_tool make no session.
            "other_spans_ignored",
            [Span("t9", "s", "http GET", 1, 2, {"http.method": "GET"})],
            {},
        ),
    ],
)
def test_sessions_from_spans(name: str, spans: list[Span], expected: dict[str, list[str]]) -> None:
    assert {s.id: shape(s.steps) for s in sessions(spans)} == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"stringValue": "x"}, "x"),
        ({"intValue": "3"}, 3),
        ({"doubleValue": 0.5}, 0.5),
        ({"boolValue": True}, True),
        ({"arrayValue": {"values": [{"stringValue": "a"}, {"intValue": "1"}]}}, ["a", 1]),
        ({"kvlistValue": {"values": [{"key": "k", "value": {"stringValue": "v"}}]}}, {"k": "v"}),
    ],
)
def test_otlp_attribute_values(value: dict[str, Any], expected: Any) -> None:
    request = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "ab",
                                "spanId": "cd",
                                "startTimeUnixNano": "1000000000",
                                "endTimeUnixNano": "2000000000",
                                "attributes": [{"key": "k", "value": value}],
                                "status": {"code": "STATUS_CODE_ERROR"},
                            }
                        ]
                    }
                ]
            }
        ]
    }
    (span,) = otlp_spans(request)
    assert (span.attributes["k"], span.start, span.end, span.error) == (expected, 1.0, 2.0, True)


@pytest.mark.parametrize(
    ("start", "end", "count"),
    [(None, None, 16), (0, None, 16), (None, 0, 0), (4e9, None, 0)],
)
def test_the_file_source_reads_a_time_window(
    start: float | None, end: float | None, count: int
) -> None:
    assert len(list(OtlpFile(RECORDED).spans(start, end))) == count


def test_rebuilt_steps_carry_their_time_in_order() -> None:
    for session in sessions(OtlpFile(RECORDED).spans()):
        times = [s.at for s in session.steps]
        assert None not in times and times == sorted(times), session.id


@pytest.mark.parametrize(
    "span",
    [
        Span(
            "t1",
            "s1",
            "agent.turn",
            1.5,
            2.25,
            {"agent.captured": "False", "n": 3, "x": 0.5, "ok": True},
        ),
        Span(
            "t1",
            "s2",
            "agent.tool",
            1.6,
            1.7,
            {"tags": ["a", "b"], "kv": {"k": "v"}},
            parent_id="s1",
            error=True,
            status_message="boom",
        ),
    ],
)
def test_a_span_written_as_otlp_reads_back_the_same(span: Span, tmp_path: Path) -> None:
    from evalharness.traces import write_otlp

    path = tmp_path / "copy.jsonl"
    assert write_otlp([span], path, service="fnol") == 1
    (back,) = OtlpFile(path).spans()
    assert back == span


@pytest.mark.parametrize(
    ("spans", "unrecorded"),
    [
        ([chat("t1", 1, [u("hi")], [a("hello")])], set()),
        ([Span("t1", "c", "chat", 1, 2, {"gen_ai.operation.name": "chat"})], {"text"}),
        (
            [
                Span(
                    "t1",
                    "x",
                    "execute_tool",
                    1,
                    2,
                    {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "get_order"},
                )
            ],
            {"arguments", "results"},
        ),
        ([tool("t1", 1, "get_order", "x1", {"id": 7})], set()),
    ],
)
def test_a_rebuilt_session_says_what_its_spans_do_not_hold(
    spans: list[Span], unrecorded: set[str]
) -> None:
    (session,) = sessions(spans)
    assert set(session.unrecorded) == unrecorded
