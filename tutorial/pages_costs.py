"""The second engine: cost rules over a day of calls, as ordinary verdicts."""

import tempfile
from html import escape
from pathlib import Path

import sources
from kit import arrow, box, fig, note, table
from pages_session import code
from reg import link, page, review, status


def _run(scenario):
    """llm-cost-explainer's own synthetic day, through our adapter, at build time."""
    try:
        from lce.synth import generate

        from evalharness.costs import LlmCostExplainer
    except ImportError:
        return None
    with tempfile.TemporaryDirectory() as d:
        return LlmCostExplainer(generate(Path(d), scenario)).run()


@page("arch-costs", "The second engine: cost rules", "arch",
      "Rules over a day of calls, not one conversation, from llm-cost-explainer.", short="Cost rules")
def arch_costs():
    d = "".join([
        box(20, 40, 240, 90, "Usage export", ["OpenAI or Anthropic,", "a day of calls"], "bxs"),
        arrow(260, 85, 320, 85),
        box(320, 30, 280, 110, "llm-cost-explainer", ["its YAML + SQL rules", "on DuckDB (a library,", "still its own product)"], "bx"),
        arrow(600, 85, 660, 85),
        box(660, 40, 220, 90, "LlmCostExplainer", ["one verdict per rule"], "solid"),
        arrow(880, 85, 940, 85),
        box(940, 40, 160, 90, "Same sinks,", ["same weekly", "report"], "bxs"),
    ])
    sections = []
    for scenario, words in [("bulk_realtime", "a nightly job sent through the real-time API"),
                            ("deprecated_model", "a model that retires next month still in use")]:
        results = _run(scenario)
        if results is None:
            sections.append(f"<p>{status(False, 'llm-cost-explainer is not installed where this page was built')}</p>")
            continue
        rows = [[f"<code>{r.evaluator}</code>", escape(r.label) or "—", f"<b>{r.verdict}</b>",
                 escape(r.reason[:160])] for r in results]
        sections.append(f"<h3>A day with {escape(words)}</h3>" + table(["Rule", "What it finds", "Verdict", "Why"], rows))
    built = [c for c in sources.cost_rules() if c["built"]]
    return f"""
<div class="text">
<p>The five patterns judge one conversation. Most cost waste can't be seen in one
conversation: “a nightly job paying real-time prices” or “a cache that expires before
it's reused” only shows across a whole day of calls. So cost rules run on a second
engine: <b>llm-cost-explainer</b>, our own product, used here as a library. It reads a
provider's usage export and runs its rules (YAML plus SQL on DuckDB).</p>
<p>Our adapter turns each of its rules into an ordinary verdict, so cost goes to the
same App Insights events and the same {link("trace-report", "weekly report")} as everything else.</p>
</div>
{fig(1120, 170, d, "The cost engine", "A day of calls in, one verdict per rule out, into the same places as every other check.")}
{table(["Rule outcome", "Verdict", "Why"], [
    ["Found waste", "<b>fail</b>, one finding per API key or model, with the monthly saving", "So the report can rank by money"],
    ["Ran, found nothing", "<b>pass</b>", ""],
    ["The export lacks what the rule needs", "<b>skip</b>: could not judge", "An export with no hourly data can't show a nightly job; that's never a pass"],
])}
<h2>Run when this page was built</h2>
<div class="text"><p>llm-cost-explainer's own made-up days, each with a known mistake, through our adapter:</p></div>
{''.join(sections)}
{note("How far the cost pack is", f"<p>{len(built)} of 36 rules are built ({', '.join(c['id'] for c in built)}); every one now runs through this framework. The other 30 come next in Tier 5, in an order you choose. The full list is on {link('cat-any', 'checks for any agent')}.</p>")}
{code("src/evalharness/costs.py", r"^def results_of", r"^def _version", "Each rule as a verdict, in real code")}
{review("arch-costs", "Cost rules", [
    "Which cost rules matter most to your clients? This sets the order of the remaining 30.",
])}
"""
