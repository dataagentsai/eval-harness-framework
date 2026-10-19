"""Phoenix as a trace source: spans from a Phoenix server's REST API.

`GET v1/projects/{project}/spans` with `start_time`, `end_time`, `limit` and a
`cursor` for the next page, answering `{data: [span], next_cursor}`; each span
has `name`, `context.trace_id`, `context.span_id`, `parent_id`, `start_time`
and `end_time` (ISO), `status_code` (`OK`, `ERROR`, `UNSET`), `status_message`
and `attributes`. Taken from Phoenix's own client (arize-phoenix-client 3.5,
whose types are generated from the server's OpenAPI document). Plain HTTP
with the standard library, so no SDK is needed.

Phoenix may hand attributes back nested (`{"llm": {"input_messages": [...]}}`);
they are flattened to the dotted names the instrumentors wrote
(`llm.input_messages.0.message.role`). Spans written by Phoenix's own
instrumentors use OpenInference names; `traces.sessions` translates those, so a
Phoenix project rebuilds into the same sessions as any other source.

Built against the API's types and tested on pages shaped by them; not yet run
against a live Phoenix (the Mac this was built on had no memory to spare).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from evalharness.traces import Span

Fetch = Callable[[str, Mapping[str, str]], Mapping[str, Any]]
"""GET a URL with headers and return the JSON answer: replaceable in tests."""


class Phoenix:
    name = "phoenix"

    def __init__(
        self,
        base_url: str,
        project: str,
        *,
        api_key: str | None = None,
        page_size: int = 1000,
        fetch: Fetch | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.project = project
        self.api_key = api_key
        self.page_size = page_size
        self._fetch = fetch or _get

    def pages(self, start: datetime, end: datetime) -> Iterator[Mapping[str, Any]]:
        headers = {"accept": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        cursor: str | None = None
        while True:
            params = {
                "limit": str(self.page_size),
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            }
            if cursor:
                params["cursor"] = cursor
            project = urllib.parse.quote(self.project, safe="")
            url = f"{self.base_url}/v1/projects/{project}/spans?{urllib.parse.urlencode(params)}"
            page = self._fetch(url, headers)
            yield page
            cursor = page.get("next_cursor")
            if not cursor or not page.get("data"):
                return

    def spans(self, start: float | None = None, end: float | None = None) -> Iterator[Span]:
        until = datetime.fromtimestamp(end, UTC) if end is not None else datetime.now(UTC)
        since = (
            datetime.fromtimestamp(start, UTC) if start is not None else until - timedelta(days=30)
        )
        for page in self.pages(since, until):
            yield from (span_of(s) for s in page.get("data", ()))


def span_of(raw: Mapping[str, Any]) -> Span:
    context = raw.get("context") or {}
    return Span(
        trace_id=str(context.get("trace_id", "")),
        span_id=str(context.get("span_id", "")),
        parent_id=str(raw.get("parent_id") or ""),
        name=str(raw.get("name", "")),
        start=_time(raw["start_time"]),
        end=_time(raw.get("end_time") or raw["start_time"]),
        attributes=flatten(raw.get("attributes") or {}),
        error=str(raw.get("status_code", "")).upper() == "ERROR",
        status_message=str(raw.get("status_message") or ""),
    )


def flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Nested attributes as the dotted names they were written with; lists of
    objects become numbered (`llm.input_messages.0.message.role`)."""
    out: dict[str, Any] = {}
    for key, v in value.items():
        name = f"{prefix}{key}"
        if isinstance(v, Mapping):
            out.update(flatten(v, f"{name}."))
        elif isinstance(v, list) and v and all(isinstance(x, Mapping) for x in v):
            for i, item in enumerate(v):
                out.update(flatten(item, f"{name}.{i}."))
        else:
            out[name] = v
    return out


def _time(value: Any) -> float:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def _get(url: str, headers: Mapping[str, str]) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers=dict(headers))
    with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310 (a configured URL)
        loaded: Mapping[str, Any] = json.loads(answer.read())
        return loaded
