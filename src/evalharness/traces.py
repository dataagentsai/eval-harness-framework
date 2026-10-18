"""Traces in, sessions out: the read side of online checking.

A `TraceSource` is wherever a team's traces already land (an OTLP file the
Collector writes, Phoenix, Langfuse, App Insights). It yields `Span`s, one
neutral shape whichever store they came from. `sessions` then rebuilds each
conversation as a `Session`, the shape the domain patterns read, from spans
that follow the OpenTelemetry GenAI conventions:

- `chat` spans carry the conversation as `gen_ai.input.messages` and
  `gen_ai.output.messages` (role + parts: `text`, `tool_call`,
  `tool_call_response`), when the agent records content;
- `execute_tool` spans carry `gen_ai.tool.name`, `gen_ai.tool.call.id`,
  `.arguments` and `.result`, and an error status when the tool failed;
- `gen_ai.conversation.id` joins the turns, each usually its own trace.

Conversations without `gen_ai.conversation.id` fall back to `session.id`, then
to the trace id (one turn, one session). The conventions have no attribute for
a decision such as a hand-over or for how a conversation ended, so sessions
rebuilt here carry neither; a check that needs them reports so.

No vendor SDK and no OpenTelemetry SDK is imported: an OTLP file is JSON.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from evalharness.core import Session, Step

CONVERSATION_KEYS = ("gen_ai.conversation.id", "session.id")
"""Span attributes that name a conversation, the standard one first."""


@dataclass(frozen=True)
class Span:
    """One span, whichever store it came from. Times in seconds since the epoch."""

    trace_id: str
    span_id: str
    name: str
    start: float
    end: float
    attributes: Mapping[str, Any] = field(default_factory=dict)
    parent_id: str = ""
    error: bool = False
    status_message: str = ""


@runtime_checkable
class TraceSource(Protocol):
    """The port: where a team's traces already are. Read-only."""

    @property
    def name(self) -> str: ...

    def spans(self, start: float | None = None, end: float | None = None) -> Iterator[Span]:
        """Spans that started in `[start, end)`; either bound may be open."""
        ...


# --------------------------------------------------------------------- OTLP


class OtlpFile:
    """OTLP JSON, as the Collector's file exporter writes it: one export
    request per line. Ids are hex and times nanosecond strings (OTLP spec)."""

    name = "otlp_file"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def spans(self, start: float | None = None, end: float | None = None) -> Iterator[Span]:
        with self.path.open(encoding="utf-8") as lines:
            for line in lines:
                if line.strip():
                    yield from _window(otlp_spans(json.loads(line)), start, end)


def otlp_spans(request: Mapping[str, Any]) -> Iterator[Span]:
    """The spans of one OTLP JSON export request."""
    for resource in request.get("resourceSpans", ()):
        for scope in resource.get("scopeSpans", ()):
            for raw in scope.get("spans", ()):
                status = raw.get("status") or {}
                yield Span(
                    trace_id=raw["traceId"],
                    span_id=raw["spanId"],
                    parent_id=raw.get("parentSpanId", ""),
                    name=raw.get("name", ""),
                    start=int(raw.get("startTimeUnixNano", 0)) / 1e9,
                    end=int(raw.get("endTimeUnixNano", 0)) / 1e9,
                    attributes={
                        a["key"]: _otlp_value(a["value"]) for a in raw.get("attributes", ())
                    },
                    # 2 is STATUS_CODE_ERROR; the JSON may also spell the enum's name.
                    error=status.get("code") in (2, "STATUS_CODE_ERROR"),
                    status_message=status.get("message", ""),
                )


def _otlp_value(value: Mapping[str, Any]) -> Any:
    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "arrayValue" in value:
        return [_otlp_value(v) for v in value["arrayValue"].get("values", ())]
    if "kvlistValue" in value:
        return {
            kv["key"]: _otlp_value(kv["value"]) for kv in value["kvlistValue"].get("values", ())
        }
    return None


def _window(spans: Iterable[Span], start: float | None, end: float | None) -> Iterator[Span]:
    for span in spans:
        if (start is None or span.start >= start) and (end is None or span.start < end):
            yield span


# ----------------------------------------------------------------- sessions


def conversation_of(span: Span) -> str:
    for key in CONVERSATION_KEYS:
        if span.attributes.get(key):
            return str(span.attributes[key])
    return span.trace_id


def sessions(spans: Iterable[Span]) -> list[Session]:
    """Each conversation in `spans`, rebuilt as a `Session`, oldest first."""
    groups: dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        if _operation(span) in ("chat", "execute_tool"):
            groups[conversation_of(span)].append(span)
    built = [_session(key, group) for key, group in groups.items()]
    return [s for _, s in sorted(built, key=lambda pair: pair[0])]


def _session(key: str, group: list[Span]) -> tuple[float, Session]:
    group.sort(key=lambda s: (s.start, s.end))
    timed: list[tuple[float, int, Step]] = []
    users: set[tuple[str, str]] = set()
    calls: set[str] = set()
    results: set[str] = set()

    def add(at: float, step: Step) -> None:
        timed.append((at, len(timed), step))

    for span in group:
        if _operation(span) == "execute_tool":
            a = span.attributes
            call_id = str(a.get("gen_ai.tool.call.id", ""))
            name = str(a.get("gen_ai.tool.name", ""))
            if not call_id or call_id not in calls:
                calls.add(call_id)
                add(
                    span.start,
                    Step(
                        "tool_call",
                        name=name,
                        call_id=call_id,
                        arguments=_object(a.get("gen_ai.tool.call.arguments")),
                    ),
                )
            if not call_id or call_id not in results:
                results.add(call_id)
                add(
                    span.end,
                    _result(
                        name,
                        call_id,
                        a.get("gen_ai.tool.call.result"),
                        span.error,
                        span.status_message,
                    ),
                )
            continue
        inputs = _messages(span.attributes.get("gen_ai.input.messages"))
        for text in _new_user_texts(inputs):
            if (span.trace_id, text) not in users:
                users.add((span.trace_id, text))
                add(span.start, Step("user", text=text))
        names = {}
        for message in inputs:
            for part in message.get("parts", ()):
                if part.get("type") == "tool_call":
                    names[str(part.get("id", ""))] = str(part.get("name", ""))
                elif part.get("type") == "tool_call_response":
                    call_id = str(part.get("id", ""))
                    if call_id and call_id not in results:
                        results.add(call_id)
                        add(
                            span.start,
                            _result(
                                names.get(call_id, ""), call_id, part.get("response"), False, ""
                            ),
                        )
        for message in _messages(span.attributes.get("gen_ai.output.messages")):
            for part in message.get("parts", ()):
                if part.get("type") == "text" and part.get("content"):
                    add(span.end, Step("assistant", text=str(part["content"])))
                elif part.get("type") == "tool_call":
                    call_id = str(part.get("id", ""))
                    if not call_id or call_id not in calls:
                        calls.add(call_id)
                        add(
                            span.end,
                            Step(
                                "tool_call",
                                name=str(part.get("name", "")),
                                call_id=call_id,
                                arguments=_object(part.get("arguments")),
                            ),
                        )

    steps: list[Step] = []
    turn = 0
    for at, _, step in sorted(timed, key=lambda t: (t[0], t[1])):
        if step.kind == "user":
            turn += 1
        steps.append(replace(step, turn=turn, at=at))
    return group[0].start, Session(id=key, steps=tuple(steps))


def _operation(span: Span) -> str:
    return str(span.attributes.get("gen_ai.operation.name", ""))


def _new_user_texts(messages: list[Mapping[str, Any]]) -> list[str]:
    """The user's words after the model last spoke: what this call was asked
    anew. Earlier turns are history the agent resent. A user message with no
    text (some frameworks send tool results as `role: user`) is not one."""
    texts: list[str] = []
    for message in messages:
        if message.get("role") == "assistant":
            texts = []
        elif message.get("role") == "user":
            words = " ".join(
                str(p.get("content", ""))
                for p in message.get("parts", ())
                if p.get("type") == "text"
            ).strip()
            if words:
                texts.append(words)
    return texts


def _result(name: str, call_id: str, raw: Any, error: bool, message: str) -> Step:
    value = _json(raw)
    return Step(
        "tool_result",
        name=name,
        call_id=call_id,
        result=value,
        text=raw if isinstance(raw, str) else (message or ""),
        is_error=error,
    )


def _messages(raw: Any) -> list[Mapping[str, Any]]:
    value = _json(raw)
    return [m for m in value if isinstance(m, Mapping)] if isinstance(value, list) else []


def _object(raw: Any) -> dict[str, object]:
    value = _json(raw)
    return dict(value) if isinstance(value, Mapping) else {}


def _json(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw
