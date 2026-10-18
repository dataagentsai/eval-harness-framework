"""Run a team's session patterns over real conversations: the agent's own
behaviour scenarios, driven by AgentTwin with tracing on, each conversation
rebuilt from its spans by the harness (`agent_harness.watch.sessions`).

Run from the agent's repository, in its environment:

    cd ~/claims-fnol-azure
    uv run --extra dev python ~/eval-harness-framework/scripts/patterns_on_scenarios.py \\
        --binding evals.gate_binding:open_subject \\
        --config ~/eval-harness-framework/examples/claims-fnol.yaml \\
        ../clean-ai-engineering/gates/motor-claims-fnol/scenarios

Scripted model, no network: the same conversations every run. Prints, per
pattern, how many conversations it judged and every violation with the
scenario it came from; `--json` writes the full results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from agent_harness import telemetry as tel
from agent_harness.watch import record
from agent_harness.watch.sessions import sessions
from agenttwin.binding import load_binding
from agenttwin.runner import ScenarioResult, run_suite, scenario_paths

from evalharness import EvalRequest
from evalharness.config import load


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--binding", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--json")
    p.add_argument("--dump", default="", help="print conversations from matching scenarios")
    p.add_argument("scenarios", nargs="+")
    args = p.parse_args()

    checks = {n: c for n, c in load(args.config).items() if c.needs == {"session"}}
    exporter = tel.configure(capture_payloads=True)
    ended: list[tuple[float, str]] = []

    def done(result: ScenarioResult) -> None:
        ended.append((time.time(), result.file))

    results = asyncio.run(
        run_suite(scenario_paths(args.scenarios), load_binding(args.binding), on_result=done)
    )
    nodes = record.from_spans(exporter.get_finished_spans())
    turns = record.turns(nodes)
    found = sessions(turns, record.background(nodes))
    started = {t.session_id or t.run_id: t.started for t in turns}

    def scenario_of(session_id: str) -> str:
        at = started.get(session_id, 0.0)
        return next((f for end, f in ended if at <= end), "?")

    print(f"{len(results)} scenarios, {len(turns)} turns, {len(found)} conversations\n")
    for s in found:
        if args.dump and args.dump in scenario_of(s.id):
            print(f"--- {scenario_of(s.id)} ({s.id}, ended {s.outcome})")
            for step in s.steps:
                detail = step.text or json.dumps(step.arguments or step.result, default=str)
                flag = " [not done]" if step.is_error else ""
                print(f"    {step.kind:11} {step.name:16} {detail[:150]}{flag}")
    out = []
    for name, check in checks.items():
        verdicts = [(s, check.evaluate(EvalRequest(session=s))) for s in found]
        judged = [(s, r) for s, r in verdicts if r.reason != "nothing to check"]
        failed = [(s, r) for s, r in judged if r.verdict == "fail"]
        print(f"{name}: {len(judged)} conversations had something to check, {len(failed)} failed")
        for s, r in failed:
            for f in r.findings:
                print(f"    {scenario_of(s.id):58} {f.kind}: {f.label}")
        out += [
            {
                "check": name,
                "scenario": scenario_of(s.id),
                "session": s.id,
                "verdict": r.verdict,
                "reason": r.reason,
                "findings": [f.label for f in r.findings],
            }
            for s, r in verdicts
        ]
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
