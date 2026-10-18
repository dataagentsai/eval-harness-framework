"""The three-part adapter every provider's check is built from.

`to_provider` and `from_provider` are pure and tested offline against recorded
answers; `call` is the only part that touches the vendor. `call` returns the
provider's answer as plain JSON whatever shape the SDK used (a dict, a mutated
metric object, a list of entities), so it can be recorded once as a fixture.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, ClassVar, Literal

from evalharness.core import EvalRequest, EvalResult, Outcome, Scale, Speed
from evalharness.judge_model import JudgeModel

Stability = Literal["alpha", "beta", "stable", "deprecated"]


class Adapter:
    kind: ClassVar[str]
    """The registry name, as `evaluators.yaml` writes it (`adapter: <kind>`)."""
    version: ClassVar[str]
    """The provider SDK version this mapping was written and recorded against."""
    provider: ClassVar[str]
    needs: ClassVar[frozenset[str]]
    carries: ClassVar[frozenset[str]]
    """Which inputs the provider's shape has room for."""
    wants: ClassVar[frozenset[str] | None] = None
    """What the check would judge on if the provider had room: `carries` when
    `None`. Only inputs it wants and cannot carry are reported `dropped`."""
    lossy: ClassVar[tuple[str, ...]] = ()
    """What is carried but loses detail on the way (passage ids, call ids)."""
    speed: ClassVar[Speed]
    expected_ms: ClassVar[float]
    default_scale: ClassVar[Scale]
    uses_judge: ClassVar[bool] = False
    stability: ClassVar[Stability] = "alpha"
    obligations: ClassVar[tuple[str, ...]] = ()
    """The AI Assurance Catalog obligations (`AAC-####`) this check helps
    discharge, whatever the agent: what links it to the standard."""

    def __init__(
        self,
        *,
        name: str | None = None,
        judge: JudgeModel | None = None,
        scale: Scale | None = None,
        description: str = "",
        requirements: Sequence[str] = (),
    ) -> None:
        self.name = name or self.kind
        self.description = description
        """The rule in plain words, for reports: what an ops reader sees beside the verdict."""
        self.requirements = tuple(requirements)
        """The requirements this rule tests, by id in the team's spec (`P-PAYOUT`,
        `escalation.injury-reported`): what links it to what must be true."""
        self.judge = judge
        self.scale = scale or self.default_scale

    # -- the three parts -------------------------------------------------------

    def to_provider(self, request: EvalRequest) -> Any:
        raise NotImplementedError

    def call(self, payload: Any) -> Mapping[str, Any]:
        raise NotImplementedError

    def from_provider(self, raw: Mapping[str, Any], request: EvalRequest) -> EvalResult:
        raise NotImplementedError

    # -- shared ----------------------------------------------------------------

    def dropped(self, request: EvalRequest) -> tuple[str, ...]:
        present = request.provides()
        wanted = present & (self.wants if self.wants is not None else self.carries)
        return tuple(sorted(wanted - self.carries)) + tuple(
            note for note in self.lossy if note.split(".")[0].split(":")[0] in present
        )

    def evaluate(self, request: EvalRequest) -> EvalResult:
        missing = self.needs - request.provides()
        if missing:
            return self.result("skip", reason=f"skip: missing {', '.join(sorted(missing))}")
        started = time.perf_counter()
        try:
            raw = self.call(self.to_provider(request))
            result = self.from_provider(raw, request)
        except Exception as failure:  # an adapter that breaks is `error`, never `pass`
            result = self.result("error", reason=f"{type(failure).__name__}: {failure}")
        return replace(
            result,
            latency_ms=(time.perf_counter() - started) * 1000,
            dropped=self.dropped(request),
        )

    def result(self, verdict: Outcome, *, reason: str, **fields: Any) -> EvalResult:
        judged = verdict in ("pass", "fail")
        return EvalResult(
            verdict=verdict,
            score=fields.pop("score", None),
            raw_score=fields.pop("raw_score", None),
            threshold=self.scale.normalised_threshold if judged else None,
            reason=reason,
            evaluator=self.name,
            version=self.version,
            provider=self.provider,
            **fields,
        )

    def scored(self, raw_score: float, *, reason: str, **fields: Any) -> EvalResult:
        """The common case: one provider number, normalised by this check's scale."""
        return self.result(
            self.scale.verdict(raw_score),
            reason=reason,
            score=self.scale.normalise(raw_score),
            raw_score=raw_score,
            **fields,
        )
