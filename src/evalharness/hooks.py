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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from evalharness.core import EvalRequest, Evaluator, Response, Session, Step, judge

Position = Literal["pre_model", "post_model", "pre_tool", "post_tool", "reply"]
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


class Hooks:
    """The hooks of one agent, by moment. The loop calls `run`; nothing else."""

    def __init__(self) -> None:
        self.placed: list[Placed] = []

    def add(
        self,
        position: Position,
        hook: Hook,
        *,
        tools: Sequence[str] = (),
        side_effects: Sequence[str] = (),
        name: str = "",
    ) -> Hook:
        if position not in POSITIONS:
            raise ValueError(f"unknown moment {position!r}; known: {', '.join(POSITIONS)}")
        if tools and position not in ("pre_tool", "post_tool"):
            raise ValueError(
                f"{position} has no tool to match; `tools` is for pre_tool and post_tool"
            )
        label = name or getattr(hook, "__name__", "hook")
        self.placed.append(Placed(label, position, Match(tuple(tools), tuple(side_effects)), hook))
        return hook

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
        block or escalate wins; a modification is handed on to the next hook."""
        changed: Decision | None = None
        for placed in self.placed:
            if placed.position != event.position or not placed.match.matches(event):
                continue
            decision = placed.hook(event) or ALLOW
            decision = replace(decision, hook=decision.hook or placed.name)
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


def check(evaluator: Evaluator, *, on_fail: Action = "block") -> Hook:
    """Any of our checks as a hook. At `pre_tool` the call about to be made is
    added to the session first, so a session pattern judges it before it happens:
    `requires_before` can stop a refund that has no lookup."""

    def hook(event: Event) -> Decision | None:
        steps = tuple(event.session.steps) if event.session else ()
        if event.position == "pre_tool":
            steps += (Step("tool_call", name=event.tool, arguments=dict(event.arguments)),)
        session = Session(event.session.id if event.session else "", steps)
        response = Response(text=event.text) if event.position in ("post_model", "reply") else None
        result = judge(evaluator, EvalRequest(session=session, response=response))
        if result.verdict == "fail":
            return Decision(on_fail, reason=result.reason, hook=evaluator.name)
        return None

    hook.__name__ = evaluator.name
    return hook
