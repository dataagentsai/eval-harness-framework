"""Running totals across conversations: what a rule like "refunds to one
customer in 30 days" needs, which no single conversation can answer.

`StateStore` is the port: add an amount to a key, get the total within a
window. `MemoryStore` keeps it in this process (tests, one worker); a shared
store (Redis) is the same port for several workers. `limit_total` is a hook
built on it: before a tool runs, would this call take the customer's total
over the limit?
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from evalharness.hooks import Action, Decision, Event, Hook


@runtime_checkable
class StateStore(Protocol):
    def total(self, key: str, window_s: float, now: float | None = None) -> float: ...

    def add(self, key: str, amount: float, now: float | None = None) -> None: ...


class MemoryStore:
    """Totals in this process: entries older than any window asked for are kept
    until `forget_before` is called."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.entries: dict[str, list[tuple[float, float]]] = defaultdict(list)

    def total(self, key: str, window_s: float, now: float | None = None) -> float:
        at = self.clock() if now is None else now
        return sum(amount for when, amount in self.entries[key] if at - window_s < when <= at)

    def add(self, key: str, amount: float, now: float | None = None) -> None:
        self.entries[key].append((self.clock() if now is None else now, amount))

    def forget_before(self, when: float) -> None:
        for key in list(self.entries):
            self.entries[key] = [e for e in self.entries[key] if e[0] >= when]


def limit_total(
    store: StateStore,
    *,
    tool: str,
    field: str,
    max_total: float,
    window_s: float,
    on_over: Action = "escalate",
    name: str = "",
) -> tuple[Hook, Hook]:
    """Two hooks: before `tool` runs, would its `field` take this customer's
    total within the window over `max_total`? After it ran successfully, count
    it. Place the first at `pre_tool` and the second at `post_tool`, both for
    `tool`. The key is the customer (`Event.user`), so the limit is per person."""
    label = name or f"{tool}_{field}_limit"

    def before(event: Event) -> Decision | None:
        amount = _number(event.arguments.get(field))
        if amount is None or not event.user:
            return None
        so_far = store.total(f"{label}:{event.user}", window_s)
        if so_far + amount > max_total:
            return Decision(
                on_over,
                reason=f"{so_far + amount:g} in the window would pass {max_total:g}",
                hook=label,
            )
        return None

    def after(event: Event) -> Decision | None:
        amount = _number(event.arguments.get(field))
        if amount is not None and event.user and not _failed(event.result):
            store.add(f"{label}:{event.user}", amount)
        return None

    before.__name__ = label
    after.__name__ = f"{label}_count"
    return before, after


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _failed(result: object) -> bool:
    return isinstance(result, dict) and bool(result.get("is_error") or result.get("error"))
