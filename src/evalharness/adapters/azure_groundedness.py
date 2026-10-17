"""Azure AI Evaluation's groundedness, judged by any OpenAI-compatible model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evalharness.adapter import Adapter
from evalharness.core import EvalRequest, EvalResult, Scale

KEY = "groundedness"


class AzureGroundedness(Adapter):
    kind = "azure_groundedness"
    version = "azure-ai-evaluation 1.18.9"
    provider = "azure"
    needs = frozenset({"response", "context"})
    carries = frozenset({"query", "response", "context"})
    lossy = ("context.source_id: passages joined into one string",)
    speed = "online"
    expected_ms = 3000
    default_scale = Scale(raw_min=1, raw_max=5, higher_is_better=True, threshold=3)
    uses_judge = True

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

        assert self.judge is not None, "a live call needs a judge"
        evaluator = GroundednessEvaluator(  # type: ignore[no-untyped-call]
            self.judge.for_azure(), threshold=self.scale.threshold, is_reasoning_model=True
        )
        return dict(evaluator(**payload))

    def from_provider(self, raw: Mapping[str, Any], request: EvalRequest) -> EvalResult:
        return self.scored(
            float(raw[KEY]),
            reason=str(raw.get(f"{KEY}_reason", "")),
            label=str(raw.get(f"{KEY}_result", "")),
            cost=self.judge_cost(raw.get(f"{KEY}_properties")),
            raw=raw,
        )

    def judge_cost(self, properties: Any) -> float:
        """Azure reports the judge's tokens in `<metric>_properties`."""
        if self.judge is None or not isinstance(properties, Mapping):
            return 0.0
        return self.judge.cost(
            int(properties.get("prompt_tokens", 0)), int(properties.get("completion_tokens", 0))
        )
