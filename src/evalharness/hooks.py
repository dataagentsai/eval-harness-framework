"""Hooks for a loop of your own: five moments, a matcher, one decision.

A framework (Pydantic AI, LangGraph, the Agent SDKs) offers hooks around model
and tool calls. A loop you write yourself has no such thing, and adding code
"before every tool call" applies to every tool. This module gives your loop the
same thing a framework has, in two pieces:

1. **The loop reports the moment.** Five lines in your loop, one per moment:
   `hooks.run(Event("pre_tool", tool=call.name, arguments=...))`. That's the
   whole change to the loop, and it never changes again.
2. **Each hook says which moments and which tools it's for.** Targeting is a
   *matcher* on the hook, not an `if` inside the loop:

       @hooks.before_tool("issue_refund")          # this tool only
       @hooks.before_tool("issue_*")               # a family of tools
       @hooks.before_tool(side_effect="irreversible")  # every tool of a kind

Borrowed from the hooks that work: Claude Code's `PreToolUse`/`PostToolUse`
(an event plus a matcher on the tool name, answering allow, deny or a changed
input), guardrails in the agent SDKs (a check beside the call that can trip
it), and LiteLLM's pre- and post-call guardrails at the gateway. A framework
adapter (Tier 7) only translates that framework's hook into an `Event`, so a
hook written once runs in your loop, in a framework, or behind a gateway.

A hook answers with a `Decision`: allow, modify (changed arguments or text),
block (with a reason the model is told), or escalate (hand to a person).
Hooks run in the order added; the first block or escalate ends the run, and
modifications chain. Any of our checks becomes a hook with `check(...)`.
"""

from __future__ import annotations

import fnmatch
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol, runtime_checkable

from evalharness.core import EvalRequest, EvalResult, Evaluator, Response, Session, Step, judge

Position = Literal["pre_model", "post_model", "pre_tool", "post_tool", "reply"]
Mode = Literal["off", "shadow", "alert", "block"]
"""What a hook's decision is allowed to do. `shadow` runs and records what it
would have decided, and changes nothing; `alert` the same, flagged for an
alert; `block` acts; `off` doesn't run. A rule moves up from shadow only with
its precision measured and an owner (T29's companion rule)."""
MODES: tuple[Mode, ...] = ("off", "shadow", "alert", "block")
OnError = Literal["closed", "open"]
POSITIONS: tuple[Position, ...] = ("pre_model", "post_model", "pre_tool", "post_tool", "reply")
Action = Literal["allow", "modify", "block", "escalate"]


@dataclass(frozen=True)
class Event:
    """What the loop hands over at one moment."""

    position: Position
    tool: str = ""
    """The tool's name, at `pre_tool` and `post_tool`."""
    arguments: Mapping[str, Any] = field(default_factory=dict)
    result: Any = None
    """The tool's result, at `post_tool`."""
    text: str = ""
    """What goes to the model (`pre_model`), what came back (`post_model`), or the reply."""
    side_effect: str = ""
    """The tool's kind, from your tool registry or spec: `read`, `write`, `irreversible`."""
    session: Session | None = None
    """The conversation so far, for checks that read more than this moment."""
    user: str = ""
    """Whose conversation it is (the customer's id): what per-customer limits key on.
    Never sent to a vendor check."""


@dataclass(frozen=True)
class Decision:
    action: Action = "allow"
    reason: str = ""
    hook: str = ""
    """Which hook decided: what a block records and the model is told."""
    arguments: Mapping[str, Any] | None = None
    """Changed arguments, when a `pre_tool` hook modifies the call."""
    text: str | None = None
    """Changed text (a redacted reply), when a hook modifies it."""

    @property
    def stops(self) -> bool:
        return self.action in ("block", "escalate")


ALLOW = Decision()


@dataclass(frozen=True)
class Moment:
    """The settings of one moment."""

    budget_ms: float | None = None
    """How long one hook may take here. A hook declared slower is refused when
    it is added; one that runs slower is recorded as over budget."""
    on_error: OnError = "closed"
    """When a blocking hook breaks: `closed` blocks (the safe default inline),
    `open` lets the turn go on."""


@dataclass(frozen=True)
class Record:
    """What one hook did at one moment: what the trace gets. No reason text,
    which can quote the conversation; the hook's name says which rule."""

    position: Position
    hook: str
    mode: Mode
    intended: Action
    """What the hook decided."""
    applied: Action
    """What was done: `allow` for a shadow or alert hook, whatever it decided."""
    ms: float
    tool: str = ""
    over_budget: bool = False
    broke: bool = False


Hook = Callable[[Event], Decision | None]
"""A hook: `None` means allow."""


@dataclass(frozen=True)
class Match:
    """Which events a hook is for. Empty means all."""

    tools: tuple[str, ...] = ()
    """Tool names or shell-style patterns (`issue_*`)."""
    side_effects: tuple[str, ...] = ()

    def matches(self, event: Event) -> bool:
        if self.tools and not any(fnmatch.fnmatchcase(event.tool, t) for t in self.tools):
            return False
        return not self.side_effects or event.side_effect in self.side_effects


@dataclass(frozen=True)
class Placed:
    name: str
    position: Position
    match: Match
    hook: Hook
    mode: Mode = "block"
    expected_ms: float = 0.0


class Hooks:
    """The hooks of one agent, by moment. The loop calls `run`; nothing else."""

    def __init__(
        self,
        *,
        moments: Mapping[str, Moment] | None = None,
        on_record: Callable[[Record], None] | None = None,
    ) -> None:
        self.placed: list[Placed] = []
        self.moments: dict[str, Moment] = dict(moments or {})
        self.on_record = on_record
        """Called with every hook's `Record`: the place to put decisions on the trace."""

    def add(
        self,
        position: Position,
        hook: Hook,
        *,
        tools: Sequence[str] = (),
        side_effects: Sequence[str] = (),
        name: str = "",
        mode: Mode = "block",
        expected_ms: float = 0.0,
    ) -> Hook:
        if position not in POSITIONS:
            raise ValueError(f"unknown moment {position!r}; known: {', '.join(POSITIONS)}")
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; known: {', '.join(MODES)}")
        budget = self.moment(position).budget_ms
        if budget is not None and expected_ms > budget:
            raise ValueError(
                f"{name or getattr(hook, '__name__', 'hook')} takes about {expected_ms:g} ms; "
                f"{position} allows {budget:g} ms. Run it online instead."
            )
        if tools and position not in ("pre_tool", "post_tool"):
            raise ValueError(
                f"{position} has no tool to match; `tools` is for pre_tool and post_tool"
            )
        label = name or getattr(hook, "__name__", "hook")
        self.placed.append(
            Placed(
                label, position, Match(tuple(tools), tuple(side_effects)), hook, mode, expected_ms
            )
        )
        return hook

    def moment(self, position: str) -> Moment:
        return self.moments.get(position, Moment())

    def _at(
        self, position: Position, tools: tuple[str, ...], side_effect: str | Sequence[str]
    ) -> Callable[[Hook], Hook]:
        effects = (side_effect,) if isinstance(side_effect, str) else tuple(side_effect)
        effects = tuple(e for e in effects if e)
        return lambda hook: self.add(position, hook, tools=tools, side_effects=effects)

    def before_tool(
        self, *tools: str, side_effect: str | Sequence[str] = ""
    ) -> Callable[[Hook], Hook]:
        return self._at("pre_tool", tools, side_effect)

    def after_tool(
        self, *tools: str, side_effect: str | Sequence[str] = ""
    ) -> Callable[[Hook], Hook]:
        return self._at("post_tool", tools, side_effect)

    def before_model(self) -> Callable[[Hook], Hook]:
        return self._at("pre_model", (), "")

    def after_model(self) -> Callable[[Hook], Hook]:
        return self._at("post_model", (), "")

    def on_reply(self) -> Callable[[Hook], Hook]:
        return self._at("reply", (), "")

    def run(self, event: Event) -> Decision:
        """Every hook for this moment whose matcher fits, in order. The first
        block or escalate wins; a modification is handed on to the next hook.
        Shadow and alert hooks run and are recorded but change nothing; a
        blocking hook that breaks decides by the moment's `on_error`."""
        changed: Decision | None = None
        moment = self.moment(event.position)
        for placed in self.placed:
            if placed.mode == "off":
                continue
            if placed.position != event.position or not placed.match.matches(event):
                continue
            started = time.perf_counter()
            broke = False
            try:
                decision = placed.hook(event) or ALLOW
            except Exception as failure:  # noqa: BLE001 (a hook must never break the turn)
                broke = True
                fallback: Action = "block" if moment.on_error == "closed" else "allow"
                decision = Decision(fallback, reason=f"hook broke: {type(failure).__name__}")
            ms = (time.perf_counter() - started) * 1000
            decision = replace(decision, hook=decision.hook or placed.name)
            acts = placed.mode == "block"
            if self.on_record is not None:
                self.on_record(
                    Record(
                        position=event.position,
                        hook=placed.name,
                        mode=placed.mode,
                        intended=decision.action,
                        applied=decision.action if acts else "allow",
                        ms=ms,
                        tool=event.tool,
                        over_budget=moment.budget_ms is not None and ms > moment.budget_ms,
                        broke=broke,
                    )
                )
            if not acts:
                continue
            if decision.stops:
                return decision
            if decision.action == "modify":
                changed = decision
                event = replace(
                    event,
                    arguments=decision.arguments
                    if decision.arguments is not None
                    else event.arguments,
                    text=decision.text if decision.text is not None else event.text,
                )
        return changed or ALLOW


class CheckBroke(RuntimeError):
    """A check answered `error`: it tried and broke. Raised so the moment's
    `on_error` decides, as for any hook that breaks."""


@runtime_checkable
class Policy(Protocol):
    """The decide step: one check's result becomes one decision. Kept apart from
    the check, so the same check can block in one company and redact in another."""

    def decide(self, result: EvalResult, event: Event, on_fail: Action) -> Decision | None: ...


class OnFail:
    """A fail does what the rule says (`on_fail`); anything else allows."""

    def decide(self, result: EvalResult, event: Event, on_fail: Action) -> Decision | None:
        if result.verdict == "fail":
            return Decision(on_fail, reason=result.reason, hook=result.evaluator)
        return None


class Redact:
    """For text the check located (Presidio gives each finding's start and end):
    mask those parts and let the text through, instead of blocking it. A failing
    result with nothing located falls back to `on_fail`."""

    def __init__(self, mask: str = "[{kind}]") -> None:
        self.mask = mask

    def decide(self, result: EvalResult, event: Event, on_fail: Action) -> Decision | None:
        if result.verdict != "fail":
            return None
        spans = merged(
            (f.start, f.end, f.kind)
            for f in result.findings
            if f.start is not None and f.end is not None
        )
        if not spans or not event.text:
            return OnFail().decide(result, event, on_fail)
        text, cut, last = event.text, [], 0
        for start, end, kind in spans:
            cut.append(text[last:start] + self.mask.format(kind=kind))
            last = end
        cut.append(text[last:])
        return Decision(
            "modify", reason=f"{len(spans)} masked", hook=result.evaluator, text="".join(cut)
        )


def merged(spans: Any) -> list[tuple[int, int, str]]:
    """Overlapping hits as one region each, named by its widest hit: Presidio
    finds "URLs" inside an email address, and masking only the first hit would
    leave the rest of the address showing."""
    out: list[tuple[int, int, str, int]] = []
    for start, end, kind in sorted(spans):
        if out and start < out[-1][1]:
            s0, e0, k0, w0 = out[-1]
            width = end - start
            out[-1] = (s0, max(e0, end), kind if width > w0 else k0, max(w0, width))
        else:
            out.append((start, end, kind, end - start))
    return [(s0, e0, k0) for s0, e0, k0, _ in out]


def check(evaluator: Evaluator, *, on_fail: Action = "block", policy: Policy | None = None) -> Hook:
    """Any of our checks as a hook. At `pre_tool` the call about to be made is
    added to the session first, so a session pattern judges it before it happens:
    `requires_before` can stop a refund that has no lookup. A check that answers
    `error` counts as broken, so the moment's `on_error` decides (closed by
    default); it never lets the action through unnoticed."""
    decide = policy or OnFail()

    def hook(event: Event) -> Decision | None:
        steps = tuple(event.session.steps) if event.session else ()
        if event.position == "pre_tool":
            steps += (Step("tool_call", name=event.tool, arguments=dict(event.arguments)),)
        session = Session(event.session.id if event.session else "", steps)
        response = Response(text=event.text) if event.text else None
        result = judge(evaluator, EvalRequest(session=session, response=response))
        if result.verdict == "error":
            raise CheckBroke(f"{evaluator.name}: {result.reason}")
        return decide.decide(result, event, on_fail)

    hook.__name__ = evaluator.name
    return hook
