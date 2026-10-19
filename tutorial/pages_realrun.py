"""The first run on a deployed agent's real traces: FNOL in App Insights,
and the lesson it taught (what isn't recorded must never become a verdict)."""

import json
from datetime import UTC, datetime
from html import escape

import live
from kit import arrow, box, fig, note, table
from reg import link, page, review, status

RUN = live.ROOT / "docs" / "runs" / "fnol-app-insights-2026-10-19.json"


def _day(ts):
    return datetime.fromtimestamp(ts, UTC).strftime("%d %b %Y")


@page("trace-real", "A real agent's traces: FNOL in App Insights", "traces",
      "The first run on a deployed agent, and the lesson it taught.", short="Real traces: FNOL")
def trace_real():
    run = json.loads(RUN.read_text())
    flow = "".join([
        box(20, 40, 210, 90, "App Insights", ["FNOL's deployed traces", "(Azure)"], "bxs"),
        arrow(230, 85, 280, 85, "KQL", ly=75),
        box(280, 40, 220, 90, "AppInsights source", ["evalharness: rows", "become spans"], "solid"),
        arrow(500, 85, 550, 85),
        box(550, 40, 230, 90, "OTLP file copy", ["read anywhere, even", "without the Azure SDK"], "bxm"),
        arrow(780, 85, 830, 85),
        box(830, 40, 270, 90, "FNOL's own rebuilder", ["turns and conversations,", "then the rules"], "bx"),
    ])
    rules = [[f"<code>{n}</code>", f"<code>{r['kind']}</code>",
              ", ".join(f"{k}: {v}" for k, v in r.items() if k != "kind")] for n, r in run["rules"].items()]
    return f"""
<div class="text">
<p>Until now every check ran on recorded test conversations. This page is the
first run on a <b>deployed</b> agent: FNOL's traces, read from its App Insights in
Azure, with read-only access. The numbers below come from that run (counts only,
saved in <code>docs/runs/</code>).</p>
</div>
{fig(1120, 160, flow, "How the traces were read", "App Insights to spans to a file copy to FNOL's own rebuilder. Only spans named agent.* and gen_ai.* are read, so HTTP calls (and anything in their URLs) never leave Azure.")}
<h2>What was there</h2>
{table(["", "Found"], [
    ["Spans read", run["spans"]],
    ["Turns", f"{run['turns']} ({_day(run['first'])} to {_day(run['last'])}, one test user)"],
    ["Turns with the conversation's words", f"<b>{run['captured']}</b>: content capture is off"],
    ["Turns with a conversation id", f"<b>{run['with_session']}</b>: the deployed build predates the fix that adds it"],
    ["How turns ended", "<br>".join(f"{escape(k)}: {v}" for k, v in run["endings"].items())],
    ["Tool calls", "<br>".join(f"{escape(k)}: {v}" for k, v in run["tools"].items())],
])}
<h2>The lesson: missing evidence must never become a verdict</h2>
<div class="text">
<p>The first run reported <b>two over-escalations</b>: payouts sent for approval
“with no rule calling for it”. They were false alarms. Those payouts were sent
for approval because the claim was over ₹25,000, but the claim's amount wasn't in
the traces, because content capture is off. The rule found no amount and read that as “not
over ₹25,000”. The hand-over rule had the same flaw: it passed turns whose customer
words it never saw.</p>
<p>The fix, now in the code:</p>
<ol>
<li>A session says what its source didn't record: <code>unrecorded</code> = text, tool arguments, tool results.</li>
<li>Each condition in a rule has three answers: yes, no, or <b>unknown</b>, when it needs something unrecorded that could have changed the answer.</li>
<li>A check that can't judge says <b>skip: could not judge</b>, with the reason. A partly judged one says how much it couldn't judge.</li>
</ol>
<p>Structure is still judged: “two tool calls failed in a row” or “a payout with no
claim read at all” need no words, so those checks still pass or fail.</p>
</div>
<h2>The rules on FNOL's real traces, after the fix</h2>
{table(["Rule", "Pattern", "Results"], rules)}
{table(["Saved question", "Rows"], [[f"<code>{k}</code>", v] for k, v in run["questions"].items()])}
{note("What this means for the product", "<p>A production agent with privacy on records <i>what happened</i> (tools, outcomes, endings) but not <i>what was said</i>. Reading its traces afterwards can check structure, not content. Content checks (promises, facts, the customer's words) have to run where the content is: inside the agent's own environment, inline or just after the turn, with only the verdicts sent to App Insights. That's the next step.</p>")}
{review("trace-real", "Real traces", [
    ("For content checks on a production agent, where should they run?",
     "Inside the agent's environment, where the words already are; only verdicts go to App Insights, so no customer words leave. Content capture stays off in production (T30, 19 Oct). Built: see the next page."),
])}
<p class="deeper">Code: <code>evalharness/sources/app_insights.py</code>, <code>scripts/pull_app_insights.py</code>,
<code>scripts/checks_on_traces.py</code>. Where checks can run: {link("arch-modes", "offline, inline, online")}. {status(True, "App Insights source")}</p>
"""
