"""DeepEval's tool correctness, in its deterministic mode.

Given `available_tools`, the same metric also asks an LLM to grade tool
selection: a different speed and cost from one constructor argument. This
adapter never passes them, so `tool_definitions` are dropped and it is inline-fast.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_harness.evals import EvalRequest

from spike.adapter import Adapter
from spike.canonical import Finding, Result, Scale
from spike.judge import Judge


class DeepEvalToolCorrectness(Adapter):
    name = "deepeval_tool_correctness"
    version = "deepeval 4.3.1"
    provider = "deepeval"
    needs = frozenset({"tool_calls", "expected"})
    carries = frozenset({"query", "response", "tool_calls", "tool_results", "expected"})
    wants = carries | {"tool_definitions"}
    lossy = (
        "tool_results.call_id: results matched to calls by tool name",
        "expected.actions: only names compared, arguments ignored",
    )
    speed = "inline"
    expected_ms = 5
    scale = Scale(raw_min=0, raw_max=1, higher_is_better=True, threshold=1.0)

    def __init__(self, judge: Judge | None = None) -> None:
        self._judge = judge
        """Never asked anything in this mode, but DeepEval builds a model when
        the metric is built and refuses without a key, so one is handed in."""

    def to_provider(self, request: EvalRequest) -> Any:
        from deepeval.test_case import LLMTestCase, ToolCall

        assert request.response is not None and request.expected is not None
        results = {r.name: r.structured for r in request.response.tool_results or ()}
        return LLMTestCase(
            input=request.query or "",
            actual_output=request.response.text,
            tools_called=[
                ToolCall(name=c.name, input_parameters=c.arguments, output=results.get(c.name))
                for c in request.response.tool_calls or ()
            ],
            expected_tools=[ToolCall(name=n) for n in request.expected.must_call],
        )

    def call(self, payload: Any) -> Mapping[str, Any]:
        from deepeval.metrics import ToolCorrectnessMetric

        assert self._judge is not None, "DeepEval builds a model even when unused"
        metric = ToolCorrectnessMetric(
            threshold=self.scale.threshold,
            async_mode=False,
            include_reason=True,
            model=self._judge.for_deepeval(),
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

    def from_provider(self, raw: Mapping[str, Any], request: EvalRequest) -> Result:
        called = set(raw["tools_called"])
        missing = [n for n in raw["expected_tools"] if n not in called]
        return self.scored(
            float(raw["score"]),
            reason=str(raw.get("reason") or ""),
            label="success" if raw.get("success") else "failure",
            findings=tuple(Finding("missing_tool", 1.0, label=n) for n in missing),
            raw=raw,
        )
