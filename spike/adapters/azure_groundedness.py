"""Azure AI Evaluation's groundedness, judged by any OpenAI-compatible model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_harness.contracts import Usage
from agent_harness.cost import cost_of, price_of
from agent_harness.evals import EvalRequest

from spike.adapter import Adapter
from spike.canonical import Result, Scale
from spike.judge import Judge

KEY = "groundedness"


class AzureGroundedness(Adapter):
    name = "azure_groundedness"
    version = "azure-ai-evaluation 1.18.9"
    provider = "azure"
    needs = frozenset({"response", "context"})
    carries = frozenset({"query", "response", "context"})
    lossy = ("context.source_id: passages joined into one string",)
    speed = "online"
    expected_ms = 3000
    scale = Scale(raw_min=1, raw_max=5, higher_is_better=True, threshold=3)

    def __init__(self, judge: Judge | None = None) -> None:
        self._judge = judge

    def to_provider(self, request: EvalRequest) -> dict[str, str]:
        assert request.response is not None and request.context is not None
        payload = {
            "response": request.response.text,
            "context": "\n\n".join(passage.text for passage in request.context),
        }
        if request.query is not None:
            payload["query"] = request.query
        return payload

    def call(self, payload: dict[str, str]) -> Mapping[str, Any]:
        from azure.ai.evaluation import GroundednessEvaluator

        assert self._judge is not None, "a live call needs a judge"
        evaluator = GroundednessEvaluator(
            self._judge.for_azure(), threshold=self.scale.threshold, is_reasoning_model=True
        )
        return dict(evaluator(**payload))

    def from_provider(self, raw: Mapping[str, Any], request: EvalRequest) -> Result:
        return self.scored(
            float(raw[KEY]),
            reason=str(raw.get(f"{KEY}_reason", "")),
            label=str(raw.get(f"{KEY}_result", "")),
            cost=judge_cost(raw.get(f"{KEY}_properties")),
            raw=raw,
        )


def judge_cost(properties: Any) -> float:
    """Azure reports the judge's tokens and model in `<metric>_properties`."""
    if not isinstance(properties, Mapping) or "model" not in properties:
        return 0.0
    usage = Usage(
        input_tokens=int(properties.get("prompt_tokens", 0)),
        output_tokens=int(properties.get("completion_tokens", 0)),
    )
    return float(cost_of(usage, price_of(str(properties["model"]))))
