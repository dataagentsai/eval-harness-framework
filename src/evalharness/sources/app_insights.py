"""App Insights as a trace source: the spans an agent already sends to Azure.

A workspace-based App Insights resource keeps each span as a row of
`AppRequests` (server spans) or `AppDependencies` (everything else): the trace
id is `OperationId`, the span id `Id`, the start `TimeGenerated`, the length
`DurationMs`, and every attribute a string in `Properties`. This module reads
those rows with one KQL query and yields `Span`s, the shape every trace source
yields, so nothing downstream knows the spans came from Azure.

Three parts, like a check's adapter: `query` builds the KQL, `call` runs it
(the only part that imports the Azure SDK), `spans_of` turns rows into spans.
Rows recorded once are enough to test the last part offline.

Only spans whose name starts with one of `prefixes` are read. That keeps HTTP
calls out, and with them anything an HTTP span names in its URL (a tenant id
in a token endpoint, a vault secret's name): what isn't read can't leak.
Attributes App Insights adds itself (`_MS.*`) are dropped.

Requires the `appinsights` extra and a credential Azure accepts (`az login`
locally; a managed identity in Azure). Reads only.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from evalharness.traces import Span

TABLES = ("AppRequests", "AppDependencies")
COLUMNS = (
    "TimeGenerated",
    "DurationMs",
    "OperationId",
    "Id",
    "ParentId",
    "Name",
    "Success",
    "Properties",
)
"""Exactly what is read: nothing else leaves the workspace."""

VERDICTS = (
    "AppTraces | where isnotempty(Properties['gen_ai.evaluation.name'])"
    " | project TimeGenerated, OperationId, Properties | order by TimeGenerated asc"
)
"""The verdict events, and only the columns a report reads."""


class AppInsights:
    name = "app_insights"

    def __init__(
        self,
        workspace_id: str,
        *,
        prefixes: Sequence[str] = ("agent.", "gen_ai."),
        credential: Any = None,
        client: Any = None,
    ) -> None:
        self.workspace_id = workspace_id
        self.prefixes = tuple(prefixes)
        self._credential = credential
        self._client = client

    def query(self) -> str:
        names = " or ".join(f"Name startswith {json.dumps(p)}" for p in self.prefixes)
        return (
            f"union {', '.join(TABLES)}"
            + (f" | where {names}" if names else "")
            + f" | project {', '.join(COLUMNS)} | order by TimeGenerated asc"
        )

    def call(
        self, start: datetime, end: datetime, query: str | None = None
    ) -> list[dict[str, Any]]:
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus

        if self._client is None:
            if self._credential is None:
                from azure.identity import DefaultAzureCredential

                self._credential = DefaultAzureCredential()
            self._client = LogsQueryClient(self._credential)
        answer = self._client.query_workspace(
            self.workspace_id, query or self.query(), timespan=(start, end)
        )
        if answer.status != LogsQueryStatus.SUCCESS:
            raise RuntimeError(
                f"App Insights query failed: {getattr(answer, 'partial_error', answer)}"
            )
        table = answer.tables[0]
        columns = [getattr(c, "name", c) for c in table.columns]
        return [dict(zip(columns, row, strict=True)) for row in table.rows]

    def verdict_rows(self, start: float, end: float) -> list[dict[str, Any]]:
        """The verdicts our sink wrote (`gen_ai.evaluation.result` events, kept by
        App Insights in `AppTraces`), as `{at, trace, attributes}`."""
        rows = self.call(
            datetime.fromtimestamp(start, UTC), datetime.fromtimestamp(end, UTC), VERDICTS
        )
        return [
            {
                "at": _time(r["TimeGenerated"]),
                "trace": str(r.get("OperationId") or ""),
                "attributes": json.loads(r["Properties"])
                if isinstance(r["Properties"], str)
                else dict(r["Properties"] or {}),
            }
            for r in rows
        ]

    def spans(self, start: float | None = None, end: float | None = None) -> Iterator[Span]:
        until = datetime.fromtimestamp(end, UTC) if end is not None else datetime.now(UTC)
        since = (
            datetime.fromtimestamp(start, UTC) if start is not None else until - timedelta(days=30)
        )
        yield from spans_of(self.call(since, until))


def spans_of(rows: Iterable[Mapping[str, Any]]) -> Iterator[Span]:
    """App Insights rows as spans. Every attribute stays the string App Insights
    stored; a reader that wants a number or a flag converts it."""
    for row in rows:
        started = _time(row["TimeGenerated"])
        properties = row.get("Properties") or {}
        if isinstance(properties, str):
            properties = json.loads(properties) if properties else {}
        yield Span(
            trace_id=str(row["OperationId"]),
            span_id=str(row["Id"]),
            parent_id=str(row.get("ParentId") or ""),
            name=str(row["Name"]),
            start=started,
            end=started + float(row.get("DurationMs") or 0) / 1000,
            attributes={k: v for k, v in properties.items() if not k.startswith("_MS.")},
            error=str(row.get("Success")).lower() == "false",
        )


def _time(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
