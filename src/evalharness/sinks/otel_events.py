"""Verdicts as OpenTelemetry `gen_ai.evaluation.result` events.

The event is the GenAI conventions' own (decision T23): `gen_ai.evaluation.name`,
`.score.value`, `.score.label`, `.explanation`, and `error.type` when a check
broke. It is emitted through the OpenTelemetry logs API, so it goes wherever
the agent's telemetry already goes: App Insights through the Azure Monitor
distro, any OTLP backend through the Collector. Emitted while the turn's span
is current, it is attached to that span's trace, so a verdict is found beside
the turn it judged (`OperationId` in App Insights).

What the conventions don't carry yet goes under `evalharness.*`: the verdict
(`pass`, `fail`, `skip`, `error`), provider, version, threshold, the
provider's raw score, finding kinds, the requirements the rule tests and the
standard's obligations it serves, and the session id. Lists are sent as
comma-separated text: every backend stores that the same way (App Insights
turns an array attribute into Python-looking text).

**Content-free by default** (decision T30): the explanation is counts and
finding kinds ("1 of 2 held; unsupported_fact"), never a finding's label,
which can quote what the customer or the agent said or an amount. Set
`explain="full"` only where the store may hold conversation content.
"""

from __future__ import annotations

from typing import Any, Literal

from evalharness.core import EvalRequest, EvalResult

EVENT = "gen_ai.evaluation.result"


class OtelEvents:
    name = "otel_events"

    def __init__(
        self,
        *,
        logger_provider: Any = None,
        explain: Literal["counts", "full"] = "counts",
        synthetic: bool = False,
    ) -> None:
        from opentelemetry._logs import get_logger

        self.logger = get_logger("evalharness", logger_provider=logger_provider)
        self.explain = explain
        self.synthetic = synthetic
        """Marks verdicts on test conversations, so reports can leave them out."""

    def record(
        self,
        result: EvalResult,
        *,
        rule: Any = None,
        request: EvalRequest | None = None,
        context: Any = None,
    ) -> None:
        self.logger.emit(
            event_name=EVENT,
            attributes=attributes(
                result, rule=rule, request=request, explain=self.explain, synthetic=self.synthetic
            ),
            context=context,
        )


def attributes(
    result: EvalResult,
    *,
    rule: Any = None,
    request: EvalRequest | None = None,
    explain: str = "counts",
    synthetic: bool = False,
) -> dict[str, Any]:
    """The event's attributes: the conventions' names first, ours after."""
    a: dict[str, Any] = {
        "gen_ai.evaluation.name": result.evaluator,
        "gen_ai.evaluation.score.label": label(result),
        "gen_ai.evaluation.explanation": result.reason if explain == "full" else _counts(result),
        "evalharness.verdict": result.verdict,
        "evalharness.provider": result.provider,
        "evalharness.version": result.version,
    }
    if result.score is not None:
        a["gen_ai.evaluation.score.value"] = float(result.score)
    if result.threshold is not None:
        a["evalharness.threshold"] = float(result.threshold)
    if result.raw_score is not None:
        a["evalharness.raw_score"] = float(result.raw_score)
    if result.verdict == "error":
        a["error.type"] = "_OTHER"
    kinds = sorted({f.kind for f in result.findings})
    if kinds:
        a["evalharness.finding_kinds"] = ",".join(kinds)
        a["evalharness.findings"] = len(result.findings)
    if rule is not None:
        a["evalharness.check"] = getattr(rule, "kind", "")
        if getattr(rule, "requirements", ()):
            a["evalharness.requirements"] = ",".join(rule.requirements)
        if getattr(rule, "obligations", ()):
            a["evalharness.obligations"] = ",".join(rule.obligations)
    if request is not None and request.session is not None:
        a["evalharness.session.id"] = request.session.id
    if request is not None and request.meta.trace:
        a["evalharness.trace"] = request.meta.trace
    if synthetic:
        a["evalharness.synthetic"] = True
    return a


LABELS = ("pass", "fail", "not_applicable", "skip", "error")
"""Every `gen_ai.evaluation.score.label` this sink writes (the conventions ask
each evaluator to document its labels)."""


def label(result: EvalResult) -> str:
    """The verdict, except that a check with nothing to check in a conversation
    (a payout rule where no payout happened) is `not_applicable`, not a pass, so
    a report's pass count means something was checked and held."""
    if result.verdict == "pass" and result.reason == "nothing to check":
        return "not_applicable"
    return result.verdict


def _counts(result: EvalResult) -> str:
    """The reason without content: what a check counted and what kinds it found.
    Only our own checks' reasons start with a count ("1 of 2 held"); another
    provider's reason may be a model's words about the conversation, so it is
    left out entirely."""
    reason = result.reason
    if result.verdict == "skip":
        head = "could not judge" if reason.startswith("could not judge") else "skip"
    elif result.provider == "ours":
        head = reason.split(";")[0].strip()
    else:
        head = result.verdict
    kinds = sorted({f.kind for f in result.findings})
    return head + (f"; {', '.join(kinds)}" if kinds else "")
