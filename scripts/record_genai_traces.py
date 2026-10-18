"""Record a third-party agent's own OpenTelemetry traces as an OTLP JSON fixture.

The agent is Pydantic AI with its built-in instrumentation, which follows the
OpenTelemetry GenAI conventions; the model is scripted (`FunctionModel`), so
no model is called and the run is the same every time. What it writes is what
a Collector's file exporter writes: one OTLP JSON export request per line.

    ~/reference-agent/.venv/bin/python scripts/record_genai_traces.py

It runs in reference-agent's environment, which has Pydantic AI; evalharness
itself never imports it. Re-run after upgrading Pydantic AI; a changed fixture
is the diff to review.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.instrumented import InstrumentationSettings

OUT = Path(__file__).parents[1] / "tests" / "fixtures" / "otlp" / "pydantic_ai_refunds.jsonl"

ORDERS = {"42": {"order_id": "42", "status": "returned", "total": 500}}

# What the scripted model does, per conversation: each entry is one model reply.
SCRIPTS: dict[str, list[ModelResponse]] = {
    # Looks the order up, then refunds it: what the rule wants.
    "conv-lookup-first": [
        ModelResponse(parts=[ToolCallPart("get_order", {"order_id": "42"}, "call_a1")]),
        ModelResponse(
            parts=[ToolCallPart("issue_refund", {"order_id": "42", "amount": 500}, "call_a2")]
        ),
        ModelResponse(parts=[TextPart("Your refund of 500 for order 42 has been issued.")]),
        # Second turn of the same conversation.
        ModelResponse(parts=[TextPart("You're welcome.")]),
    ],
    # Refunds without looking the order up: requires_before fails.
    "conv-no-lookup": [
        ModelResponse(
            parts=[ToolCallPart("issue_refund", {"order_id": "42", "amount": 500}, "call_b1")]
        ),
        ModelResponse(parts=[TextPart("Done, your refund of 500 is on its way.")]),
    ],
    # The lookup fails; the agent says so and does nothing else.
    "conv-tool-error": [
        ModelResponse(parts=[ToolCallPart("get_order", {"order_id": "99"}, "call_c1")]),
        ModelResponse(parts=[TextPart("I couldn't find order 99. Could you check the number?")]),
    ],
}

TURNS = {
    "conv-lookup-first": ["Please refund order 42.", "Thanks!"],
    "conv-no-lookup": ["Refund order 42 now."],
    "conv-tool-error": ["Where is my refund for order 99?"],
}


def scripted(conversation: str) -> FunctionModel:
    replies = iter(SCRIPTS[conversation])

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return next(replies)

    return FunctionModel(reply, model_name="scripted")


def agent_for(conversation: str, provider: TracerProvider) -> Agent[None, str]:
    agent = Agent(
        scripted(conversation),
        name="refund-agent",
        instructions="You handle refunds. Look the order up before refunding it.",
    )
    agent.instrument = InstrumentationSettings(tracer_provider=provider, include_content=True)

    @agent.tool_plain
    def get_order(order_id: str) -> dict[str, Any]:
        """Look an order up."""
        if order_id not in ORDERS:
            raise ModelRetry(f"order {order_id} not found")
        return ORDERS[order_id]

    @agent.tool_plain
    def issue_refund(order_id: str, amount: int) -> dict[str, Any]:
        """Refund an order."""
        return {"order_id": order_id, "refunded": amount}

    return agent


def otlp_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [otlp_value(v) for v in value]}}
    return {"stringValue": str(value)}


def otlp_span(span: ReadableSpan) -> dict[str, Any]:
    """One span in OTLP JSON: ids in hex, times as nanosecond strings (OTLP spec)."""
    context = span.get_span_context()
    assert context is not None
    out: dict[str, Any] = {
        "traceId": f"{context.trace_id:032x}",
        "spanId": f"{context.span_id:016x}",
        "name": span.name,
        "kind": span.kind.value + 1,
        "startTimeUnixNano": str(span.start_time),
        "endTimeUnixNano": str(span.end_time),
        "attributes": [
            {"key": k, "value": otlp_value(v)} for k, v in (span.attributes or {}).items()
        ],
        "status": {"code": span.status.status_code.value},
    }
    if span.parent is not None:
        out["parentSpanId"] = f"{span.parent.span_id:016x}"
    if span.status.description:
        out["status"]["message"] = span.status.description
    return out


def main() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    for conversation, turns in TURNS.items():
        agent = agent_for(conversation, provider)
        history: list[ModelMessage] = []
        for text in turns:
            run = agent.run_sync(text, message_history=history, conversation_id=conversation)
            history = run.all_messages()
    spans = exporter.get_finished_spans()
    request = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": otlp_value("refund-agent")}]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "pydantic-ai"},
                        "spans": [otlp_span(s) for s in spans],
                    }
                ],
            }
        ]
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(request, ensure_ascii=False) + "\n")
    print(f"{len(spans)} spans -> {OUT}")
    for s in spans:
        attrs = s.attributes or {}
        print(f"  {s.name:40} op={attrs.get('gen_ai.operation.name')}")


if __name__ == "__main__":
    main()
