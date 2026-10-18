"""Copy an agent's spans from App Insights into an OTLP JSON file.

    .venv/bin/python scripts/pull_app_insights.py \\
        --resource-group rg-claims-fnol-dev --workspace-name log-fnol-<suffix> \\
        --days 30 --out /path/to/private/fnol.jsonl

Reads only, with your `az login`. The file holds real telemetry (user ids,
trace ids): keep it out of the repository. `OtlpFile` reads it back anywhere,
including an agent's own environment that has no Azure SDK.
"""

from __future__ import annotations

import argparse
import subprocess
import time

from evalharness.sources.app_insights import AppInsights
from evalharness.traces import write_otlp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", help="the Log Analytics workspace id (customerId)")
    ap.add_argument("--resource-group")
    ap.add_argument("--workspace-name")
    ap.add_argument("--days", type=float, default=30)
    ap.add_argument(
        "--prefix", action="append", help="span name prefixes (default: agent., gen_ai.)"
    )
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    workspace = (
        a.workspace
        or subprocess.check_output(
            [
                "az",
                "monitor",
                "log-analytics",
                "workspace",
                "show",
                "-g",
                a.resource_group,
                "-n",
                a.workspace_name,
                "--query",
                "customerId",
                "-o",
                "tsv",
            ],
            text=True,
        ).strip()
    )
    source = AppInsights(workspace, prefixes=a.prefix or ("agent.", "gen_ai."))
    spans = list(source.spans(time.time() - a.days * 86400))
    n = write_otlp(spans, a.out)
    print(f"{n} spans from {len({s.trace_id for s in spans})} traces -> {a.out}")


if __name__ == "__main__":
    main()
