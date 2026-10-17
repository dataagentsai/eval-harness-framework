"""Checks as plug-ins: one request in, one result out, whichever provider judges.

Every evaluator — our rules, Presidio, an Azure evaluator, DeepEval, Ragas, an
open judge model — sits behind one port, `Evaluator`, is handed one shape,
`EvalRequest`, and answers in one shape, `EvalResult`. A provider's own shape
stays inside its adapter (`evalharness.adapter`, `evalharness.adapters`).

Extracted from `agent_harness.evals` (reference-agent), which now re-exports
these names; the additions from the spike (FINDINGS.md) are `Finding`, `Scale`
and `EvalResult`'s `raw`, `findings` and `dropped`, all defaulted, so every
existing construction is unchanged.

**Each evaluator declares what it needs.** A request that lacks it is
`skip: missing <input>`, never a failure, so a turn with no retrieval is not
failed by a groundedness check.

No vendor SDK is imported here or anywhere outside its own adapter module (an
import-contract test holds that line).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Outcome = Literal["pass", "fail", "skip", "error"]
"""An evaluator's verdict. `skip`: it could not judge (an input was missing);
`error`: it tried and broke, which inline fails closed."""

Speed = Literal["inline", "online", "offline"]
"""How long an evaluator may take, as a class: `inline` fits inside a
customer's wait, `online` runs after the turn, `offline` only in a batch."""

NEEDS = (
    "query",
    "messages",
    "response",
    "tool_calls",
    "tool_results",
    "tool_definitions",
    "context",
    "expected",
)
"""Every input an evaluator may declare it needs: the request's fields, with
the response's tool calls and results named apart because a reply can be
judged on its text where its tools were not recorded."""


class ToolCallLike(Protocol):
    """A tool call as any host records it: the harness's `ToolCall` is one."""

    @property
    def id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def arguments(self) -> Mapping[str, object]: ...


class ToolResultLike(Protocol):
    """A tool result as any host records it: the harness's `ToolResult` is one.
    It carries no call id, so a result is matched to its call by tool name."""

    @property
    def name(self) -> str: ...
    @property
    def structured(self) -> object: ...
    @property
    def text(self) -> str: ...
    @property
    def is_error(self) -> bool: ...


@dataclass(frozen=True)
class Response:
    """The reply, with its tool calls and their results. `None` for calls or
    results means *not recorded*; an empty tuple means *none were made*."""

    text: str
    tool_calls: tuple[ToolCallLike, ...] | None = None
    tool_results: tuple[ToolResultLike, ...] | None = None
    gateway: tuple[Mapping[str, str], ...] = ()
    """What a gateway said about each model call behind this reply (APIM's
    `x-content-safety`): empty where there was no gateway or it was not recorded."""


@dataclass(frozen=True)
class Passage:
    """One retrieved passage, with the id of the source it came from."""

    source_id: str
    text: str


@dataclass(frozen=True)
class Expected:
    """What a golden case says should happen. Only a golden case has one."""

    route: str | None = None
    must_call: tuple[str, ...] = ()
    must_not_call: tuple[str, ...] = ()
    must_include: tuple[str, ...] = ()
    actions: tuple[Mapping[str, Any], ...] = ()
    """The expected actions, as `{name, arguments}`: what an action-matching
    evaluator compares the tool calls with."""


@dataclass(frozen=True)
class Meta:
    agent: str = ""
    version: str = ""
    trace: str = ""
    position: str = ""
    """Where this request is being judged: an inline position, `online` or `release`."""
    language: str = "en"
    user: str = ""
    """Whose turn it was (the customer id). Never sent to a vendor evaluator."""


@dataclass(frozen=True)
class EvalRequest:
    """What every evaluator is handed. Conversation and tools in OpenAI's
    message and tool formats, so a vendor adapter maps fields, not shapes."""

    query: str | None = None
    messages: tuple[Mapping[str, Any], ...] | None = None
    response: Response | None = None
    tool_definitions: tuple[Mapping[str, Any], ...] | None = None
    """The tools this customer was allowed, as OpenAI function definitions."""
    context: tuple[Passage, ...] | None = None
    expected: Expected | None = None
    meta: Meta = field(default_factory=Meta)

    def provides(self) -> frozenset[str]:
        """The inputs present on this request, in `NEEDS`' words."""
        response = self.response
        present = {
            "query": self.query is not None,
            "messages": self.messages is not None,
            "response": response is not None,
            "tool_calls": response is not None and response.tool_calls is not None,
            "tool_results": response is not None and response.tool_results is not None,
            "tool_definitions": self.tool_definitions is not None,
            "context": self.context is not None,
            "expected": self.expected is not None,
        }
        return frozenset(name for name, here in present.items() if here)


@dataclass(frozen=True)
class Finding:
    """One thing a check found. A check can find many (one per PII entity)."""

    kind: str
    """What was found: `PERSON`, `EMAIL_ADDRESS`, `violence`, `missing_tool`."""
    confidence: float
    """0–1: how sure the provider is. Not how bad it is: Presidio is surer of a
    date than of a URL, and neither is as bad as an email address."""
    severity: float | None = None
    """0–1, 1 worst: how bad this kind is, set by configuration per `kind`, or
    by the provider when it judges harm itself."""
    start: int | None = None
    end: int | None = None
    """Where in the response text, when the provider says: what a redaction needs."""
    label: str = ""


@dataclass(frozen=True)
class Scale:
    """A provider's number, described, so it can become our 0–1 with 1 best.
    Configured per check (`evaluators.yaml`), not written into the adapter."""

    raw_min: float
    raw_max: float
    higher_is_better: bool
    threshold: float
    """In the provider's own units, as its docs state it; inclusive."""

    def normalise(self, raw: float) -> float:
        span = self.raw_max - self.raw_min
        share = (min(max(raw, self.raw_min), self.raw_max) - self.raw_min) / span
        return share if self.higher_is_better else 1.0 - share

    @property
    def normalised_threshold(self) -> float:
        return self.normalise(self.threshold)

    def verdict(self, raw: float) -> Outcome:
        return "pass" if self.normalise(raw) >= self.normalised_threshold else "fail"


@dataclass(frozen=True)
class EvalResult:
    """What every evaluator answers, whichever provider it is."""

    verdict: Outcome
    score: float | None
    """Normalised to 0–1, 1 best. `None` when skipped or errored."""
    raw_score: float | None
    """The provider's own number (a 1–5 rating, a 0/1), before normalising."""
    threshold: float | None
    """What `score` was judged against: pass when `score >= threshold`."""
    reason: str
    evaluator: str
    """The configured name: which plug-in this is in `evaluators.yaml`."""
    version: str
    provider: str
    """`ours`, `azure`, an open model's name: whose judgement this is."""
    cost: float = 0.0
    """What the call cost, in USD (tokens or a fee); feeds the cost engine."""
    latency_ms: float = 0.0
    label: str = ""
    """The provider's own label for the outcome (Azure returns one beside its
    score); for a rule, the id its verdict names."""
    raw: Mapping[str, Any] = field(default_factory=dict)
    """The provider's answer, untouched: for audit, and to re-read when the
    mapping changes."""
    findings: tuple[Finding, ...] = ()
    dropped: tuple[str, ...] = ()
    """What the request lost on its way into the provider's shape (passage ids,
    tool definitions), so a lossy result is labelled, not trusted silently."""

    @property
    def failed(self) -> bool:
        return self.verdict == "fail"


@runtime_checkable
class Evaluator(Protocol):
    """The port. One adapter per provider; one instance per configured name."""

    @property
    def name(self) -> str: ...
    @property
    def version(self) -> str: ...
    @property
    def provider(self) -> str: ...
    @property
    def needs(self) -> frozenset[str]: ...
    @property
    def speed(self) -> Speed: ...
    @property
    def expected_ms(self) -> float:
        """The declared cost class in time: what an inline position's `max_ms`
        is compared with at startup."""
        ...

    def evaluate(self, request: EvalRequest) -> EvalResult: ...


def skipped(evaluator: Evaluator, missing: frozenset[str]) -> EvalResult:
    """The result for a request that lacks what `evaluator` needs."""
    return EvalResult(
        verdict="skip",
        score=None,
        raw_score=None,
        threshold=None,
        reason=f"skip: missing {', '.join(sorted(missing))}",
        evaluator=evaluator.name,
        version=evaluator.version,
        provider=evaluator.provider,
    )


def judge(evaluator: Evaluator, request: EvalRequest) -> EvalResult:
    """Run one evaluator, or skip it when the request lacks what it needs."""
    missing = evaluator.needs - request.provides()
    if missing:
        return skipped(evaluator, frozenset(missing))
    return evaluator.evaluate(request)
