"""DeepEval's tool correctness, in its deterministic mode.

Given `available_tools`, the same metric also asks an LLM to grade tool
selection: a different speed and cost from one constructor argument. This
adapter never passes them, so `tool_definitions` are dropped and it needs no
model call, though DeepEval still builds a model and refuses without a key.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evalharness.adapter import Adapter
from evalharness.core import EvalRequest, EvalResult, Finding, Scale


class DeepEvalToolCorrectness(Adapter):
    kind = "deepeval_tool_correctness"
    obligations = ("AAC-0051",)
    version = "deepeval 4.3.1"
    provider = "deepeval"
    needs = frozenset({"tool_calls", "expected"})
    carries = frozenset({"query", "response", "tool_calls", "tool_results", "expected"})
    wants = carries | {"tool_definitions"}
    lossy = (
        "tool_results.call_id: results matched to calls by tool name",
        "expected.actions: only names compared, arguments ignored",
    )
    speed = "online"
    expected_ms = 500
    """Measured live (17 Oct): about 500 ms per call even with no model call,
    because DeepEval builds its model objects each time. Not inline-fast."""
    default_scale = Scale(raw_min=0, raw_max=1, higher_is_better=True, threshold=1.0)
    uses_judge = True

    def to_provider(self, request: EvalRequest) -> Any:
        from deepeval.test_case import LLMTestCase, ToolCall

        assert request.response is not None and request.expected is not None
        results = {r.name: r.structured for r in request.response.tool_results or ()}
        return LLMTestCase(
            input=request.query or "",
            actual_output=request.response.text,
            tools_called=[
                ToolCall(
                    name=c.name, input_parameters=dict(c.arguments), output=results.get(c.name)
                )
                for c in request.response.tool_calls or ()
            ],
            expected_tools=[
                ToolCall(name=n, input_parameters={}) for n in request.expected.must_call
            ],
        )

    def call(self, payload: Any) -> Mapping[str, Any]:
        from deepeval.metrics import ToolCorrectnessMetric

        assert self.judge is not None, "DeepEval builds a model even when it is unused"
        metric = ToolCorrectnessMetric(
            threshold=self.scale.threshold,
            async_mode=False,
            include_reason=True,
            model=self.judge.for_deepeval(),
        )
        metric.measure(payload, _show_indicator=False)
        # DeepEval answers by mutating the metric; this is that state, as JSON.
        return {
            "score": metric.score,
            "reason": metric.reason,
            "success": metric.success,
            "tools_called": [t.name for t in payload.tools_called],
            "expected_tools": [t.name for t in payload.expected_tools],
        }

    def from_provider(self, raw: Mapping[str, Any], request: EvalRequest) -> EvalResult:
        called = set(raw["tools_called"])
        missing = [n for n in raw["expected_tools"] if n not in called]
        return self.scored(
            float(raw["score"]),
            reason=str(raw.get("reason") or ""),
            label="success" if raw.get("success") else "failure",
            findings=tuple(Finding("missing_tool", 1.0, severity=1.0, label=n) for n in missing),
            raw=raw,
        )
