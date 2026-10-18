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
    "session",
)
"""Every input an evaluator may declare it needs: the request's fields, with
the response's tool calls and results named apart because a reply can be
judged on its text where its tools were not recorded. `session` is the whole
conversation, for checks no single turn can answer."""


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


StepKind = Literal["user", "assistant", "tool_call", "tool_result", "decision"]
HUMAN = "human"
"""The name of an `assistant` step a person wrote, after a hand-over."""


@dataclass(frozen=True)
class Step:
    """One thing that happened in a session, in order.

    A `decision` is something the agent or the harness decided outside a tool
    call, such as `escalate` or a guardrail's `blocked`; a host records it
    under that name. A person's reply after a hand-over is an `assistant` step
    named `human`: checks on the agent's own words skip it."""

    kind: StepKind
    name: str = ""
    """The tool's name for a call or result; the decision's name for a decision."""
    text: str = ""
    arguments: Mapping[str, object] = field(default_factory=dict)
    result: object = None
    """A tool result's structured content."""
    call_id: str = ""
    """Pairs a result with its call, where the host records it."""
    is_error: bool = False
    turn: int = 0
    at: float | None = None
    """When it happened, in seconds since the epoch, where the source records
    it (traces do; chat messages don't)."""

    @property
    def by_agent(self) -> bool:
        """An agent reply, not a person's after a hand-over."""
        return self.kind == "assistant" and self.name != HUMAN


@dataclass(frozen=True)
class Session:
    """A whole conversation: what the session-level checks read."""

    id: str
    steps: tuple[Step, ...]
    outcome: str = ""
    """How it ended, in the host's words: `resolved`, `abandoned`, `escalated`."""
    unrecorded: frozenset[str] = frozenset()
    """What the source did not record, so a check must not read its absence as
    a fact: `text` (what the customer and the agent said), `arguments` (tool
    arguments), `results` (tool results). Production traces with content
    capture off hold none of the three."""

    def calls(self, name: str | None = None) -> tuple[tuple[int, Step], ...]:
        """Tool calls, with their position in `steps`, optionally one tool's only."""
        return tuple(
            (i, s)
            for i, s in enumerate(self.steps)
            if s.kind == "tool_call" and (name is None or s.name == name)
        )

    def succeeded(self, index: int) -> bool:
        """Whether the call at `index` has a result that is not an error. A
        result is paired by call id where recorded, else the next one by name."""
        call = self.steps[index]
        for later in self.steps[index + 1 :]:
            if later.kind != "tool_result":
                continue
            if (call.call_id and later.call_id == call.call_id) or (
                not call.call_id and later.name == call.name
            ):
                return not later.is_error
        return False

    @classmethod
    def from_messages(
        cls, id: str, messages: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]]
    ) -> Session:
        """From OpenAI-format chat messages, which most frameworks can export."""
        import json

        steps: list[Step] = []
        turn = 0
        for m in messages:
            role = m.get("role")
            if role == "user":
                turn += 1
                steps.append(Step("user", text=str(m.get("content") or ""), turn=turn))
            elif role == "assistant":
                if m.get("content"):
                    steps.append(Step("assistant", text=str(m["content"]), turn=turn))
                for call in m.get("tool_calls") or ():
                    fn = call.get("function", {})
                    raw = fn.get("arguments") or "{}"
                    arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
                    steps.append(
                        Step(
                            "tool_call",
                            name=str(fn.get("name", "")),
                            arguments=arguments,
                            call_id=str(call.get("id", "")),
                            turn=turn,
                        )
                    )
            elif role == "tool":
                content = m.get("content")
                try:
                    result: object = json.loads(content) if isinstance(content, str) else content
                except ValueError:
                    result = content
                steps.append(
                    Step(
                        "tool_result",
                        name=str(m.get("name", "")),
                        text=content if isinstance(content, str) else "",
                        result=result,
                        call_id=str(m.get("tool_call_id", "")),
                        is_error=bool(m.get("is_error", False)),
                        turn=turn,
                    )
                )
        return cls(id=id, steps=tuple(steps))


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
    session: Session | None = None
    """The whole conversation, where a check judges more than one turn."""
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
            "session": self.session is not None,
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
