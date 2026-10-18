"""Run a team's rules and the saved questions over an agent's real traces.

Reads an OTLP file (`pull_app_insights.py` writes one from App Insights),
rebuilds turns and conversations with the agent harness's own reader
(`agent_harness.watch`), runs every session check in the rules file, and
answers the saved questions. Run it in the agent's environment, which has
the harness:

    cd ~/claims-fnol-azure
    uv run python ~/eval-harness-framework/scripts/checks_on_traces.py \\
        --traces /path/to/private/fnol.jsonl \\
        --config ~/eval-harness-framework/examples/claims-fnol.yaml --json out.json

What a check can judge depends on what the traces hold: with content capture
off, there is no customer text, no reply and no tool arguments, and each
result says so instead of guessing.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

from agent_harness.watch import record
from agent_harness.watch.sessions import sessions

from evalharness import EvalRequest
from evalharness.config import load
from evalharness.questions import QUESTIONS, answer
from evalharness.traces import OtlpFile


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--json")
    ap.add_argument("--summary", help="write counts only (no ids), safe to publish")
    a = ap.parse_args()
    summary: dict[str, object] = {}

    nodes = record.from_trace_spans(OtlpFile(a.traces).spans())
    turns = record.turns(nodes)
    convos = sessions(turns, record.background(nodes))
    print(f"{len(nodes)} spans, {len(turns)} turns, {len(convos)} conversations")
    print(f"  content captured on {sum(t.captured for t in turns)} of {len(turns)} turns")
    print(f"  with a conversation id: {sum(bool(t.session_id) for t in turns)} of {len(turns)}")
    print(
        "  how turns ended:",
        dict(Counter(f"{t.result}{'/' + t.rule_id if t.rule_id else ''}" for t in turns)),
    )
    endings = Counter(f"{t.result}{'/' + t.rule_id if t.rule_id else ''}" for t in turns)
    tools = Counter((u.name, u.outcome) for t in turns for u in t.tools)
    summary.update(
        spans=len(nodes),
        turns=len(turns),
        conversations=len(convos),
        captured=sum(t.captured for t in turns),
        with_session=sum(bool(t.session_id) for t in turns),
        endings=dict(endings),
        tools={f"{n} {o or 'unrecorded'}": c for (n, o), c in sorted(tools.items())},
        first=min((t.started for t in turns), default=0),
        last=max((t.started for t in turns), default=0),
        rules={},
        questions={},
    )
    print("  tool calls:", {f"{n} {o}": c for (n, o), c in sorted(tools.items())})

    checks = {n: c for n, c in load(a.config).items() if c.needs == frozenset({"session"})}
    results = []
    print("\nRules (session checks):")
    for name, check in checks.items():
        verdicts: Counter[str] = Counter()
        for convo in convos:
            r = check.evaluate(EvalRequest(session=convo))
            verdicts[r.verdict if r.reason != "nothing to check" else "nothing to check"] += 1
            results.append((check.kind, r))
        print(f"  {name:28} {dict(verdicts)}")
        summary["rules"][name] = {"kind": check.kind, **verdicts}  # type: ignore[index]

    print("\nSaved questions:")
    out = {}
    for q in QUESTIONS:
        rows = answer(q, results)
        out[q.name] = [r.__dict__ for r in rows]
        print(f"  {q.name:30} {len(rows)}")
        summary["questions"][q.name] = len(rows)  # type: ignore[index]
        for r in rows[:5]:
            print(f"      {r.session}: {r.label}")
    if a.summary:
        with open(a.summary, "w") as f:
            json.dump(summary, f, indent=2)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(
                {"turns": len(turns), "conversations": len(convos), "questions": out}, f, indent=2
            )


if __name__ == "__main__":
    main()
