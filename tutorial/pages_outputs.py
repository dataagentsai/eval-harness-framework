"""What a team gets on top of the tools it already has: results, rules,
dashboards, conversation, and saved questions answered deterministically."""

from html import escape

import live
from kit import arrow, box, fig, note, table
from reg import link, page, review, status

from evalharness import EvalRequest, Session
from evalharness.questions import QUESTIONS, answer


def _demo():
    """Run FNOL's approval rule over a few conversations and answer two saved questions."""
    ex = live.EXAMPLES["decision_vs_should"]
    rule = ex["pattern"]
    good = ex["good"]
    over = [live.u("Pay claim CLM-104233 please."), live.call("get_claim", id="CLM-104233"),
            live.ok("get_claim", live.CLAIM), live.call("request_payout", id="CLM-104233"),
            live.ok("request_payout", {"queued": True}), live.decide("awaiting_approval"),
            live.say("A colleague will approve this payout.")]
    sessions = {"conv-101 (₹61,000, approved)": good, "conv-102 (₹61,000, no approval)": ex["bad"],
                "conv-103 (₹12,400, sent for approval)": over}
    results = [("decision_vs_should", rule.evaluate(EvalRequest(session=Session(sid, tuple(steps)))))
               for sid, steps in sessions.items()]
    return sessions, results


@page("arch-outputs", "What you get on top of your tools", "arch",
      "Results, rules, dashboards, conversation and saved questions, tool by tool.", short="On top of your tools")
def arch_outputs():
    ladder = "".join([
        box(20, 30, 230, 80, "Someone asks", ["“Show last week's", "under-escalations”"], "bx"),
        arrow(250, 70, 300, 70),
        box(300, 20, 250, 100, "1 · A saved question?", ["matched by name:", "same answer every time"], "solid"),
        arrow(550, 70, 600, 70, "no", ly=60),
        box(600, 20, 250, 100, "2 · A defined metric?", ["picked from the semantic", "layer; never free SQL"], "bx"),
        arrow(850, 70, 900, 70, "no", ly=60),
        box(900, 20, 200, 100, "3 · Say so", ["“I don't have that.", "Closest: …”"], "bxm"),
        arrow(425, 120, 425, 170, "yes", lx=445, ly=150),
        arrow(725, 120, 725, 170, "yes", lx=745, ly=150),
        box(300, 170, 550, 70, "Answer with evidence", ["rows, the rule and requirement they came from, links to the traces"], "bxs"),
    ])
    sessions, results = _demo()
    under = answer(next(q for q in QUESTIONS if q.name == "under_escalations"), results)
    over = answer(next(q for q in QUESTIONS if q.name == "over_escalations"), results)
    rows = lambda found: table(["Conversation", "Rule", "What it found"],  # noqa: E731
                               [[escape(r.session), f"<code>{r.rule}</code>", escape(r.label)] for r in found]
                               or [["—", "—", "none"]])
    return f"""
<div class="text">
<p>Checks alone aren't the product. Once results exist, a team wants five things,
and for each one we ask: does their tool already do it? If yes, we feed it; we
only build what's missing.</p>
</div>
{table(["What the team wants", "Who provides it", "What we ship"], [
    ["<b>Results</b> where they already look", "Their tool (LangSmith, Langfuse, App Insights…)", "An adapter that writes each result in the tool's own shape: the rule name, pass or fail, score, reason, and the requirement ids"],
    ["<b>Rules and alerts</b> (“approval misses rose 3 days running”)", "Their tool's alerting", "Alert-rule templates per tool: KQL for Azure Monitor, PromQL for Prometheus, LangSmith/Langfuse alert settings"],
    ["<b>Dashboards</b>", "Their tool", "Two templates only (Grafana, Azure Workbook). LangSmith, Langfuse and Phoenix need none: our results show as their native scores"],
    ["<b>Conversation</b> over traces and results", "Their chat (Teams, Copilot, Claude, Genie)", "One small read-only MCP server plus metric definitions for their semantic layer (Cube or Databricks Metric Views)"],
    ["<b>Saved questions</b>, answered the same way every time", "Nobody, today", "A named list of questions with deterministic answers, compiled into each tool's form (" + status(True, "the definitions and the answer engine") + ")"],
])}

<h2>Tool by tool: LangSmith, for instance</h2>
{table(["", "LangSmith", "Langfuse / Phoenix", "App Insights (Azure)", "Prometheus + Grafana"], [
    ["Results land as", "Feedback on the same run (key = rule name)", "Scores on the same trace", "Custom events + metrics", "Counters per rule and verdict"],
    ["Rules and alerts", "Its alerts on feedback, from our template", "Its alerts, from our template", "Azure Monitor alerts in KQL, from our template", "Alertmanager rules in PromQL, from our template"],
    ["Dashboards", "Its own charts show our feedback", "Its own screens show our scores", "Our Workbook template", "Our Grafana template"],
    ["Review queue", "We push failing runs to its annotation queue", "Same, its annotation queue", "—", "—"],
    ["Saved questions", "A saved filter per question", "A saved filter per question", "A KQL query per question", "A panel per question"],
    ["Conversation", "MCP answers link to LangSmith runs", "Links to traces", "Links to traces", "Counts only"],
    ["State", status(False, "Tier 8"), status(False, "Tier 4"), status(False, "Tier 8"), status(False, "Tier 8")],
])}

<h2>Saved questions: deterministic first</h2>
<div class="text"><p>Most ops questions are asked every week: “where should it have handed over
and didn't?”, “where did it ask for approval it didn't need?”. Those must never
depend on how an AI phrases a query. So each one is <b>saved</b>: a name, plus a
filter over the results (which pattern, which kind of finding). Dashboards, alerts
and the chat all use the same definition.</p></div>
{fig(1120, 260, ladder, "How a question is answered", "The chat tries the saved questions first, then the defined metrics, and otherwise says it doesn't know. It never writes its own SQL or KQL.")}
{table(["Saved question", "What it asks", "Reads"], [[f"<code>{q.name}</code>", escape(q.title), f"<code>{q.pattern}</code> findings of kind <code>{q.finding}</code>"] for q in QUESTIONS])}

<h2>Try it: under- and over-escalations</h2>
<div class="text"><p>FNOL's approval rule (a person approves payouts over ₹25,000) ran on three
conversations when this page was built. Then the two saved questions were answered from the results:</p></div>
{table(["Conversation", "Approval rule"], [[escape(sid), f"<b>{r.verdict}</b>: {escape(r.reason)}"] for sid, (_, r) in zip(sessions, results, strict=True)])}
<h3><code>under_escalations</code></h3>
{rows(under)}
<h3><code>over_escalations</code></h3>
{rows(over)}
{note("Why this matters", "<p>The same three conversations will always give exactly these rows, whoever asks and however they phrase it. That's what lets a weekly report, a dashboard panel and a chat answer agree with each other.</p>")}
{review("arch-outputs", "On top of your tools", [
    ("Which saved questions would an ops lead ask first? Six are built in; what's missing from the list?",
     "Under- and over-escalations and promises not kept first, then actions without a prerequisite. Add next: “a tool kept failing and nobody took over”."),
    ("For a LangSmith client, is “results as feedback, alerts and saved filters from our templates, chat through MCP” the right offer?",
     "Yes: results as feedback on the same run, alert and saved-filter templates, the chat through MCP. No LangSmith dashboard template."),
])}
<p class="deeper">Source: <code>src/evalharness/questions.py</code>. The conversation design is in {link("arch", "Architecture")} and PLAN.html.</p>
"""
