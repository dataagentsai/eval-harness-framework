"""App Insights as a trace source, tested on rows shaped as the workspace returns them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from evalharness.sources.app_insights import COLUMNS, AppInsights, spans_of
from evalharness.traces import TraceSource


def row(**over: Any) -> dict[str, Any]:
    base = {
        "TimeGenerated": "2026-10-14T14:18:15.5Z",
        "DurationMs": 250.0,
        "OperationId": "a" * 32,
        "Id": "b" * 16,
        "ParentId": "c" * 16,
        "Name": "agent.turn",
        "Success": True,
        "Properties": '{"agent.turn.result": "escalated", "_MS.ResourceAttributeId": "x"}',
    }
    return {**base, **over}


START = datetime(2026, 10, 14, 14, 18, 15, 500000, tzinfo=UTC).timestamp()


@pytest.mark.parametrize(
    ("given", "field", "expected"),
    [
        (row(), "start", START),
        (row(), "end", START + 0.25),
        (row(TimeGenerated=datetime.fromtimestamp(START, UTC)), "start", START),
        (row(), "attributes", {"agent.turn.result": "escalated"}),  # _MS.* dropped
        (row(Properties={"k": "v"}), "attributes", {"k": "v"}),  # already parsed
        (row(Properties=""), "attributes", {}),
        (row(Success=False), "error", True),
        (row(Success="False"), "error", True),
        (row(Success=True), "error", False),
        (row(ParentId=None), "parent_id", ""),
        (row(), "trace_id", "a" * 32),
    ],
)
def test_a_row_becomes_a_span(given: dict[str, Any], field: str, expected: Any) -> None:
    (span,) = spans_of([given])
    assert getattr(span, field) == expected


@pytest.mark.parametrize(
    ("prefixes", "has", "lacks"),
    [
        (("agent.", "gen_ai."), ['Name startswith "agent."', 'Name startswith "gen_ai."'], []),
        ((), [], ["where"]),
    ],
)
def test_the_query_reads_only_named_spans_and_columns(
    prefixes: tuple[str, ...], has: list[str], lacks: list[str]
) -> None:
    kql = AppInsights("ws", prefixes=prefixes).query()
    assert all(h in kql for h in has) and not any(x in kql for x in lacks)
    assert f"project {', '.join(COLUMNS)}" in kql


@dataclass
class _Column:
    name: str


class _Client:
    """Answers like LogsQueryClient: one table, columns and rows."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, Any]] = []

    def query_workspace(self, workspace_id: str, query: str, *, timespan: Any) -> Any:
        from azure.monitor.query import LogsQueryStatus

        self.asked.append((workspace_id, query, timespan))
        r = row()
        table = type(
            "T", (), {"columns": [_Column(c) for c in COLUMNS], "rows": [[r[c] for c in COLUMNS]]}
        )
        return type("A", (), {"status": LogsQueryStatus.SUCCESS, "tables": [table]})()


def test_the_source_queries_its_workspace_for_the_window() -> None:
    pytest.importorskip("azure.monitor.query")
    client = _Client()
    source = AppInsights("ws-1", client=client)
    assert isinstance(source, TraceSource)
    (span,) = source.spans(START - 60, START + 60)
    workspace, _, (since, until) = client.asked[0]
    assert workspace == "ws-1" and span.name == "agent.turn"
    assert (since.timestamp(), until.timestamp()) == (START - 60, START + 60)
