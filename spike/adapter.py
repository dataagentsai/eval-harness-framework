"""The three-part adapter: `to_provider` and `from_provider` are pure, `call` is
the only part that touches the vendor.

`call` returns the provider's answer as plain JSON, whatever shape the SDK used
(a dict, a mutated metric object, a list of entities), so that answer can be
recorded once as a fixture and `from_provider` tested against it with no network.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, ClassVar

from agent_harness.evals import EvalRequest, Speed

from spike.canonical import Result, Scale


class Adapter:
    name: ClassVar[str]
    version: ClassVar[str]
    """The provider SDK's version this mapping was written and recorded against."""
    provider: ClassVar[str]
    needs: ClassVar[frozenset[str]]
    carries: ClassVar[frozenset[str]]
    """Which of the request's inputs the provider's shape has room for. What the
    request has and this lacks is reported as `dropped`."""
    wants: ClassVar[frozenset[str] | None] = None
    """What this check would judge on if the provider had room: `carries` when
    `None`. Only inputs it wants and cannot carry are `dropped`, so a PII check
    is not reported as dropping the query it never needed."""
    lossy: ClassVar[tuple[str, ...]] = ()
    """What is carried but loses detail on the way (passage ids, call ids)."""
    speed: ClassVar[Speed]
    expected_ms: ClassVar[float]
    scale: ClassVar[Scale]

    def to_provider(self, request: EvalRequest) -> Any:
        raise NotImplementedError

    def call(self, payload: Any) -> Mapping[str, Any]:
        raise NotImplementedError

    def from_provider(self, raw: Mapping[str, Any], request: EvalRequest) -> Result:
        raise NotImplementedError

    def dropped(self, request: EvalRequest) -> tuple[str, ...]:
        present = request.provides()
        wanted = present & (self.wants if self.wants is not None else self.carries)
        return tuple(sorted(wanted - self.carries)) + tuple(
            note for note in self.lossy if note.split(".")[0] in present
        )

    def evaluate(self, request: EvalRequest) -> Result:
        missing = self.needs - request.provides()
        if missing:
            return self._result("skip", reason=f"skip: missing {', '.join(sorted(missing))}")
        started = time.perf_counter()
        try:
            raw = self.call(self.to_provider(request))
            result = self.from_provider(raw, request)
        except Exception as failure:  # an adapter that breaks is `error`, never `pass`
            result = self._result("error", reason=f"{type(failure).__name__}: {failure}")
        return replace(
            result,
            latency_ms=(time.perf_counter() - started) * 1000,
            dropped=self.dropped(request),
        )

    def _result(self, verdict: str, *, reason: str, **fields: Any) -> Result:
        return Result(
            verdict=verdict,  # type: ignore[arg-type]
            score=fields.pop("score", None),
            raw_score=fields.pop("raw_score", None),
            threshold=self.scale.normalised_threshold if verdict in ("pass", "fail") else None,
            reason=reason,
            evaluator=self.name,
            version=self.version,
            provider=self.provider,
            **fields,
        )

    def scored(self, raw_score: float, *, reason: str, **fields: Any) -> Result:
        """The common case: one provider number, normalised by this check's scale."""
        return self._result(
            self.scale.verdict(raw_score),
            reason=reason,
            score=self.scale.normalise(raw_score),
            raw_score=raw_score,
            **fields,
        )
