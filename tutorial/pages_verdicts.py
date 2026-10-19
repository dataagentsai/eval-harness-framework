"""Verdicts back into App Insights: checks run where the words are, only
verdicts leave, and saved questions become KQL."""

import json
from html import escape

import live
from kit import arrow, box, fig, note, table, text
from pages_session import code, yaml_block
from reg import link, page, review

from evalharness import EvalRequest, Session
from evalharness.questions import BY_NAME, to_kql
from evalharness.sinks.otel_events import LABELS, attributes

RUN = live.ROOT / "docs" / "runs" / "fnol-verdicts-app-insights-2026-10-19.json"


@page("trace-verdicts", "Verdicts back into App Insights", "traces",
      "Checks run where the words are; only verdicts leave; saved questions become KQL.",
      short="Verdicts into App Insights")
def trace_verdicts():
    run = json.loads(RUN.read_text())
    d = "".join([
        '<rect class="zone" x="10" y="14" width="560" height="236" rx="14"/>',
        text(24, 38, "INSIDE THE AGENT'S ENVIRONMENT (the words stay here)", "lbl"),
        box(30, 60, 220, 80, "The conversation", ["words, amounts, tool", "arguments and results"], "bx"),
        arrow(250, 100, 310, 100),
        box(310, 60, 240, 80, "Our checks", ["the five patterns,", "with everything they need"], "solid"),
        box(310, 160, 240, 70, "OtelEvents sink", ["verdict, counts, kinds,", "requirement ids"], "bxs"),
        arrow(430, 140, 430, 160),
        arrow(550, 195, 640, 195, "verdicts only", ly=185),
        box(640, 150, 220, 90, "App Insights", ["AppTraces, beside", "the turn's trace"], "bxs"),
        arrow(860, 195, 920, 195),
        box(920, 60, 190, 70, "Saved questions", ["as KQL"], "bx"),
        box(920, 150, 190, 70, "Dashboards", ["workbook template"], "bxm"),
        box(920, 240, 190, 70, "Alerts", ["KQL alert rules"], "bxm"),
        '<path class="ln" d="M860 195 L890 195 L890 95 L920 95"/>',
        '<path class="ln" d="M890 195 L890 275 L920 275"/>',
    ])
    ex = live.EXAMPLES["consistency"]
    session = Session("conv-9", tuple(ex["bad"]))
    request = EvalRequest(session=session)
    result = ex["pattern"].evaluate(request)
    sent = attributes(result, rule=ex["pattern"], request=request)
    full = attributes(result, rule=ex["pattern"], request=request, explain="full")
    rows = []
    for name, by in run["by_rule"].items():
        rows.append([f"<code>{name}</code>"] + [str(by.get(lab, "")) or "—" for lab in ("pass", "fail", "not_applicable")])
    return f"""
<div class="text">
<p><b>Your decision (T30):</b> checks that need the conversation's words run where the
words already are, inside the agent's environment. Only the verdicts go to App
Insights. Content capture stays off. This page shows it working on Azure.</p>
</div>
{fig(1120, 330, d, "Checks inside, verdicts out", "The left box never sends words anywhere. App Insights receives one small event per check per conversation, next to the turn's own trace.")}
<h2>What one verdict looks like</h2>
<div class="text"><p>Each verdict is an OpenTelemetry <code>gen_ai.evaluation.result</code> event,
the standard's own shape. Our extra fields go under <code>evalharness.*</code>. Here is
the facts check failing on the made-up ₹15,000 from {link("p-consistency", "the consistency page")}.
Note the explanation: counts and kinds only. The amount the agent made up is not sent.</p></div>
{table(["Attribute", "Sent"], [[f"<code>{k}</code>", escape(str(v))] for k, v in sent.items()])}
<div class="text"><p>With <code>explain="full"</code> (only where the store may hold conversation
content), the explanation would instead read: <i>{escape(full["gen_ai.evaluation.explanation"])}</i>.</p></div>

<h2>The run on Azure</h2>
<div class="text"><p>{escape(run["run"])} Every conversation got one verdict per rule,
{run["verdicts"]} in all. Counted back from App Insights with KQL:</p></div>
{table(["Rule", "pass", "fail", "not applicable"], rows)}
{note("Not applicable is not a pass", "<p>A payout rule on a conversation with no payout had nothing to check. Counting that as a pass would make every report look better than it is, so it's labelled <code>not_applicable</code>. The labels this sink writes: " + ", ".join(f"<code>{x}</code>" for x in LABELS) + ".</p>")}

<h2>Saved questions, as App Insights queries</h2>
<div class="text"><p>Each saved question is generated into KQL from its one definition. This is
<code>under_escalations</code>. On Azure it found exactly the one deliberate under-escalation, and the
other questions found nothing.</p></div>
{yaml_block(to_kql(BY_NAME["under_escalations"]), "to_kql(under_escalations): paste into App Insights › Logs")}
{code("src/evalharness/sinks/otel_events.py", r"^def attributes", r"^LABELS", "The event, in real code")}
{review("trace-verdicts", "Verdicts into App Insights", [
    ("Is the content-free default right: counts and finding kinds, never the quoted words or amounts?",
     "Yes (19 Oct): the full explanation only where the store may hold content, such as a dev deployment."),
])}
<p class="deeper">What a team gets on top of this, tool by tool: {link("arch-outputs", "on top of your tools")}.</p>
"""
