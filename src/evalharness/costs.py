"""The cost rules: the second engine, for checks over many calls and days.

The five patterns judge one conversation. Most of the LLM cost rules
(LLM-01 to LLM-36) can't: "bulk work on the real-time API" or "a cache too
short for the traffic" only shows across a day of calls. Those run on the
rule runner (decision T7): llm-cost-explainer, used as a library, which reads
a provider's usage export and runs its YAML+SQL rules on DuckDB.

`RuleRunner` is the port: run once over a period, one `EvalResult` per rule.
`LlmCostExplainer` is the adapter. Each rule becomes:

- `fail` when it found waste: one `Finding` per scope (an API key, a model),
  its label the rule's own summary, the money it would save kept in `raw`;
- `pass` when it ran and found nothing;
- `skip`, "could not judge", when the export lacks what the rule needs (an
  export without hourly data can't show bulk work), never a pass.

So cost verdicts go to the same sinks and the same weekly report as every
other check. llm-cost-explainer stays its own product; it is imported only here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from evalharness.core import EvalResult, Finding

PROVIDER = "llm-cost-explainer"
OBLIGATIONS = ("AAC-0008",)
"""Cost per successful task (AAC-0008): the obligation every cost rule serves."""


@runtime_checkable
class RuleRunner(Protocol):
    @property
    def name(self) -> str: ...

    def run(self) -> list[EvalResult]: ...


class LlmCostExplainer:
    name = "llm_cost_explainer"
    obligations = OBLIGATIONS

    def __init__(self, paths: Sequence[str | Path], *, day: date | None = None) -> None:
        self.paths = [str(p) for p in paths]
        self.day = day

    def call(self) -> dict[str, Any]:
        from lce.analyse import analyse

        payload: dict[str, Any] = analyse(self.paths, day=self.day)
        return payload

    def run(self) -> list[EvalResult]:
        return results_of(self.call())


def results_of(payload: dict[str, Any]) -> list[EvalResult]:
    """One result per rule, from llm-cost-explainer's answer."""
    version = _version()
    found: dict[str, list[dict[str, Any]]] = {}
    for f in payload.get("findings", ()):
        found.setdefault(f["rule_id"], []).append(f)
    titles = {f["rule_id"]: f["title"] for f in payload.get("findings", ())}
    out = []
    for rule_id in sorted(set(payload.get("rules_run", ())) | set(found)):
        hits = found.get(rule_id, [])
        saving = sum(f["savings_day"] for f in hits)
        out.append(
            EvalResult(
                verdict="fail" if hits else "pass",
                score=0.0 if hits else 1.0,
                raw_score=saving,
                threshold=None,
                reason=(
                    f"{len(hits)} finding{'s' if len(hits) != 1 else ''}, "
                    f"about ${saving * 30:,.0f}/month to save; {hits[0]['summary']}"
                    if hits
                    else "nothing wasteful found"
                ),
                evaluator=rule_id,
                version=version,
                provider=PROVIDER,
                label=titles.get(rule_id, ""),
                raw={"day": payload.get("day"), "findings": hits},
                findings=tuple(
                    Finding(
                        kind=rule_id,
                        confidence=1.0,
                        label=f"{', '.join(f'{k}={v}' for k, v in f['scope'].items())}: "
                        f"${f['savings_day'] * 30:,.0f}/month",
                    )
                    for f in hits
                ),
            )
        )
    for rule_id, title, why in payload.get("skipped", ()):
        if rule_id in found or any(r.evaluator == rule_id for r in out):
            continue
        out.append(
            EvalResult(
                verdict="skip",
                score=None,
                raw_score=None,
                threshold=None,
                reason=f"could not judge: {why}",
                evaluator=rule_id,
                version=version,
                provider=PROVIDER,
                label=title,
            )
        )
    return sorted(out, key=lambda r: r.evaluator)


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("llm-cost-explainer")
    except PackageNotFoundError:
        return ""
