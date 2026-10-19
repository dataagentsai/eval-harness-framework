"""The weekly report for one agent, from the verdicts in App Insights.

    .venv/bin/python scripts/weekly_report.py \\
        --resource-group rg-claims-fnol-dev --workspace-name log-fnol-<suffix> \\
        --out report.html [--agent claims-fnol] [--include-synthetic]

Reads only verdict events (no conversation content). Test conversations
(marked synthetic) are left out unless asked for, and the page says so when
they are counted.
"""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

from evalharness.report import Verdict, to_html, weekly
from evalharness.sources.app_insights import AppInsights

WEEK = 7 * 86400


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace")
    ap.add_argument("--resource-group")
    ap.add_argument("--workspace-name")
    ap.add_argument("--agent", default="")
    ap.add_argument("--include-synthetic", action="store_true")
    ap.add_argument("--end", type=float, default=None, help="end of the week, epoch seconds")
    ap.add_argument(
        "--start",
        type=float,
        default=None,
        help="start of the period instead of a week before --end, epoch seconds "
        "(to leave out verdicts written before a format change)",
    )
    ap.add_argument("--title", default="Weekly agent report")
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
    end = a.end or time.time()
    source = AppInsights(workspace)
    rows = source.verdict_rows(end - 2 * WEEK, end)
    verdicts = [Verdict.of(r["at"], r["attributes"], r["trace"]) for r in rows]
    start = a.start or end - WEEK
    report = weekly(
        verdicts,
        start=start,
        end=end,
        # A period chosen with --start has no fair "week before" (it was chosen to
        # leave older verdicts out), so it is compared with nothing.
        previous=[] if a.start else [v for v in verdicts if end - 2 * WEEK <= v.at < start],
        agent=a.agent,
        include_synthetic=a.include_synthetic,
    )
    Path(a.out).write_text(to_html(report, title=a.title))
    print(f"{report.verdicts} verdicts this week, {len(report.rules)} rules -> {a.out}")
    for name, found in report.questions.items():
        print(f"  {name:30} {len(found)}")


if __name__ == "__main__":
    main()
