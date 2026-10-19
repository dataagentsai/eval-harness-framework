"""Phoenix as a trace source, and OpenInference spans rebuilt into sessions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from evalharness import EvalRequest
from evalharness.patterns import RequiresBefore
from evalharness.sources.phoenix import Phoenix, flatten, span_of
from evalharness.traces import Span, TraceSource, from_openinference, sessions


def phx(
    name: str, at: int, kind: str, attributes: dict[str, Any], *, status: str = "OK", span: str = ""
) -> dict[str, Any]:
    """A span as Phoenix's API answers (types from arize-phoenix-client 3.5)."""
    return {
        "name": name,
        "context": {"trace_id": "t1", "span_id": span or f"s{at}"},
        "span_kind": kind,
        "parent_id": None,
        "start_time": f"2026-10-19T10:00:{at:02d}+00:00",
        "end_time": f"2026-10-19T10:00:{at:02d}.500000+00:00",
        "status_code": status,
        "status_message": "",
        "attributes": attributes,
    }


SESSION = {"session": {"id": "conv-7"}}
# A refund agent traced by an OpenInference instrumentor, as Phoenix hands it back
# (attributes nested): the model asks for issue_refund with no order lookup first.
REFUND = [
    phx(
        "ChatCompletion",
        1,
        "LLM",
        {
            **SESSION,
            "openinference": {"span": {"kind": "LLM"}},
            "llm": {
                "input_messages": [{"message": {"role": "user", "content": "Refund order 42"}}],
                "output_messages": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "tool_call": {
                                        "id": "c1",
                                        "function": {
                                            "name": "issue_refund",
                                            "arguments": '{"order_id": "42"}',
                                        },
                                    }
                                }
                            ],
                        }
                    }
                ],
            },
        },
    ),
    phx(
        "issue_refund",
        2,
        "TOOL",
        {
            **SESSION,
            "openinference": {"span": {"kind": "TOOL"}},
            "tool": {"name": "issue_refund"},
            "tool_call": {"id": "c1"},
            "input": {"value": '{"order_id": "42"}'},
            "output": {"value": '{"refunded": 500}'},
        },
    ),
    phx(
        "ChatCompletion",
        3,
        "LLM",
        {
            **SESSION,
            "openinference": {"span": {"kind": "LLM"}},
            "llm": {
                "input_messages": [
                    {"message": {"role": "user", "content": "Refund order 42"}},
                    {
                        "message": {
                            "role": "tool",
                            "tool_call_id": "c1",
                            "content": '{"refunded": 500}',
                        }
                    },
                ],
                "output_messages": [
                    {"message": {"role": "assistant", "content": "Refunded ₹500."}}
                ],
            },
        },
    ),
]


class FakePhoenix:
    """Answers GET v1/projects/{p}/spans two spans a page, with a cursor."""

    def __init__(self, spans: list[dict[str, Any]]) -> None:
        self.spans, self.asked = spans, []

    def __call__(self, url: str, headers: Mapping[str, str]) -> Mapping[str, Any]:
        self.asked.append((url, dict(headers)))
        q = parse_qs(urlparse(url).query)
        at = int(q.get("cursor", ["0"])[0])
        page = self.spans[at : at + 2]
        nxt = str(at + 2) if at + 2 < len(self.spans) else None
        return {"data": page, "next_cursor": nxt}


def test_the_source_pages_through_a_project() -> None:
    fake = FakePhoenix(REFUND)
    source = Phoenix("http://phoenix:6006/", "refund agent", api_key="k", page_size=2, fetch=fake)
    assert isinstance(source, TraceSource)
    spans = list(source.spans(0, 2e9))
    assert [s.name for s in spans] == ["ChatCompletion", "issue_refund", "ChatCompletion"]
    first, _ = fake.asked[0]
    assert first.startswith("http://phoenix:6006/v1/projects/refund%20agent/spans?")
    assert fake.asked[0][1]["authorization"] == "Bearer k"
    assert "cursor=2" in fake.asked[1][0] and len(fake.asked) == 2


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ({"a": {"b": 1}}, {"a.b": 1}),
        (
            {"llm": {"input_messages": [{"message": {"role": "user"}}]}},
            {"llm.input_messages.0.message.role": "user"},
        ),
        ({"tags": ["x", "y"]}, {"tags": ["x", "y"]}),  # plain lists stay lists
        ({"already.flat": 2}, {"already.flat": 2}),
    ],
)
def test_nested_attributes_flatten_to_their_dotted_names(
    given: dict[str, Any], expected: dict[str, Any]
) -> None:
    assert flatten(given) == expected


@pytest.mark.parametrize(("status", "error"), [("OK", False), ("ERROR", True), ("UNSET", False)])
def test_status(status: str, error: bool) -> None:
    assert span_of(phx("x", 1, "TOOL", {}, status=status)).error is error


def test_openinference_spans_rebuild_into_a_session() -> None:
    (session,) = sessions(span_of(s) for s in REFUND)
    assert session.id == "conv-7"
    shape = [(s.kind, s.name or s.text) for s in session.steps]
    assert shape == [
        ("user", "Refund order 42"),
        ("tool_call", "issue_refund"),
        ("tool_result", "issue_refund"),
        ("assistant", "Refunded ₹500."),
    ]
    ((_, call),) = session.calls("issue_refund")
    assert (call.call_id, call.arguments) == ("c1", {"order_id": "42"})
    assert session.unrecorded == frozenset()


def test_a_pattern_catches_the_refund_with_no_lookup() -> None:
    (session,) = sessions(span_of(s) for s in REFUND)
    rule = RequiresBefore(action="issue_refund", before="get_order", same=["order_id"])
    assert rule.evaluate(EvalRequest(session=session)).verdict == "fail"


@pytest.mark.parametrize(
    ("attributes", "added"),
    [
        ({"openinference.span.kind": "CHAIN"}, {}),  # other kinds pass unchanged
        (
            {"openinference.span.kind": "TOOL", "tool.name": "get_order"},
            {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "get_order"},
        ),
        ({"openinference.span.kind": "LLM"}, {"gen_ai.operation.name": "chat"}),  # no messages kept
    ],
)
def test_only_what_was_recorded_is_translated(
    attributes: dict[str, Any], added: dict[str, Any]
) -> None:
    out = from_openinference(Span("t", "s", "x", 0, 1, attributes))
    assert {k: v for k, v in out.attributes.items() if k not in attributes} == added
