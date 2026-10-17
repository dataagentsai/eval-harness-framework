"""Ragas faithfulness, from the `ragas.metrics.collections` API.

Ragas 0.4 ships two `Faithfulness` classes: the old one in `ragas.metrics` takes a
`SingleTurnSample` (which has room for passage ids) and a LangChain-wrapped LLM;
the new one takes three plain arguments and an `instructor` LLM. The new one is
used here, so passage ids are lost.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from agent_harness.evals import EvalRequest

from spike.adapter import Adapter
from spike.canonical import Result, Scale
from spike.judge import Judge


class RagasFaithfulness(Adapter):
    name = "ragas_faithfulness"
    version = "ragas 0.4.3"
    provider = "ragas"
    needs = frozenset({"query", "response", "context"})
    carries = frozenset({"query", "response", "context"})
    lossy = ("context.source_id: passages passed as bare strings",)
    speed = "online"
    expected_ms = 6000
    scale = Scale(raw_min=0, raw_max=1, higher_is_better=True, threshold=0.7)

    def __init__(self, judge: Judge | None = None) -> None:
        self._judge = judge

    def to_provider(self, request: EvalRequest) -> dict[str, Any]:
        assert request.response is not None and request.context is not None
        return {
            "user_input": request.query or "",
            "response": request.response.text,
            "retrieved_contexts": [passage.text for passage in request.context],
        }

    def call(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        from ragas.metrics.collections import Faithfulness

        assert self._judge is not None, "a live call needs a judge"
        metric = Faithfulness(llm=self._judge.for_ragas())
        answer = asyncio.run(metric.ascore(**payload))
        return {"value": answer.value, "reason": getattr(answer, "reason", None)}

    def from_provider(self, raw: Mapping[str, Any], request: EvalRequest) -> Result:
        return self.scored(float(raw["value"]), reason=str(raw.get("reason") or ""), raw=raw)
