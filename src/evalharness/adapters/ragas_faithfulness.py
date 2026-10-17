"""Ragas faithfulness, from the `ragas.metrics.collections` API.

Ragas 0.4 ships two `Faithfulness` classes: the old one in `ragas.metrics` takes a
`SingleTurnSample` (with room for passage ids) and a LangChain-wrapped LLM; the
new one takes three plain arguments and an `instructor` LLM, and returns no
reason and no token count, so its cost reads 0. The new one is used here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from evalharness.adapter import Adapter
from evalharness.core import EvalRequest, EvalResult, Scale


class RagasFaithfulness(Adapter):
    kind = "ragas_faithfulness"
    version = "ragas 0.4.3"
    provider = "ragas"
    needs = frozenset({"query", "response", "context"})
    carries = frozenset({"query", "response", "context"})
    lossy = ("context.source_id: passages passed as bare strings",)
    speed = "online"
    expected_ms = 6000
    default_scale = Scale(raw_min=0, raw_max=1, higher_is_better=True, threshold=0.7)
    uses_judge = True

    def to_provider(self, request: EvalRequest) -> dict[str, Any]:
        assert request.response is not None and request.context is not None
        return {
            "user_input": request.query or "",
            "response": request.response.text,
            "retrieved_contexts": [passage.text for passage in request.context],
        }

    def call(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        from ragas.metrics.collections import Faithfulness

        assert self.judge is not None, "a live call needs a judge"
        metric = Faithfulness(llm=self.judge.for_ragas())
        answer = asyncio.run(metric.ascore(**payload))
        return {"value": answer.value, "reason": getattr(answer, "reason", None)}

    def from_provider(self, raw: Mapping[str, Any], request: EvalRequest) -> EvalResult:
        return self.scored(float(raw["value"]), reason=str(raw.get("reason") or ""), raw=raw)
