"""What the spike adds to `agent_harness.evals`, to test whether the hub holds.

Three additions, each named in the design discussion (17 Oct 2026):

1. `raw` — the provider's answer, untouched, kept beside our normalised one.
2. `findings` — the many things one check can find (an entity per PII hit, a
   category per harm), each with where it sits in the text: what a redaction needs.
3. `dropped` — what the request lost on its way into the provider's shape
   (passage ids, gateway headers), so a lossy result is labelled, not trusted.

And `Scale`: how a provider's number becomes our 0–1 score, declared in YAML
rather than written into each adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agent_harness.evals import EvalResult, Outcome


@dataclass(frozen=True)
class Finding:
    kind: str
    """What was found: `PERSON`, `PHONE_NUMBER`, `violence`, `unexpected_tool`."""
    confidence: float
    """0–1: how sure the provider is. Not how bad it is: Presidio is surer of a
    date than of a URL, and neither is as bad as an email address."""
    severity: float | None = None
    """0–1, 1 worst: how bad this kind is, set by policy per `kind` (YAML), or
    by the provider when it judges harm itself (Azure's 0–7 harm levels)."""
    start: int | None = None
    end: int | None = None
    """Where in the response text, when the provider says."""
    label: str = ""


@dataclass(frozen=True)
class Result(EvalResult):
    """`EvalResult` with the three additions; every existing field unchanged."""

    raw: Mapping[str, Any] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    dropped: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scale:
    """A provider's number, described: `evaluators.yaml` holds one per check."""

    raw_min: float
    raw_max: float
    higher_is_better: bool
    threshold: float
    """In the provider's own units, as its docs state it."""

    def normalise(self, raw: float) -> float:
        """The provider's number as 0–1, 1 best, clamped."""
        span = self.raw_max - self.raw_min
        share = (min(max(raw, self.raw_min), self.raw_max) - self.raw_min) / span
        return share if self.higher_is_better else 1.0 - share

    @property
    def normalised_threshold(self) -> float:
        return self.normalise(self.threshold)

    def verdict(self, raw: float) -> Outcome:
        return "pass" if self.normalise(raw) >= self.normalised_threshold else "fail"
