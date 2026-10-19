"""Result sinks: where verdicts go, in the team's own tools. One module per kind.

The port is one method: `record(result, rule=..., request=...)`. A sink never
decides anything; it writes what a check found where the team already looks.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from evalharness.core import EvalRequest, EvalResult


@runtime_checkable
class ResultSink(Protocol):
    @property
    def name(self) -> str: ...

    def record(
        self, result: EvalResult, *, rule: Any = None, request: EvalRequest | None = None
    ) -> None: ...
