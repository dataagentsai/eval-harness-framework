"""The weekly report: built from verdicts only, counted the same way every time."""

from kit import arrow, box, fig, note, table
from pages_session import code, yaml_block
from reg import link, page, review

REPORT = "reports/fnol-weekly-2026-10-19.html"


@page("trace-report", "The weekly report", "traces",
      "One agent's week, from verdicts only: rules, saved questions, broken requirements.",
      short="Weekly report")
def trace_report():
    d = "".join([
        box(20, 40, 230, 90, "App Insights", ["verdict events only"], "bxs"),
        arrow(250, 85, 310, 85, "KQL", ly=75),
        box(310, 40, 250, 90, "weekly(verdicts)", ["counts and filters,", "no model, no content"], "solid"),
        arrow(560, 85, 620, 85),
        box(620, 40, 220, 90, "A page", ["self-contained HTML,", "prints cleanly"], "bx"),
        arrow(840, 85, 900, 85, "later", ly=75),
        box(900, 40, 200, 90, "Teams / email", ["Tier 8"], "bxm"),
    ])
    return f"""
<div class="text">
<p>The weekly report is the first thing an ops lead would read. It's built only
from the verdicts in App Insights, never from conversations, so it holds no customer
content. Every number is a count and every list is a filter: the same week always
gives the same report.</p>
</div>
{fig(1120, 160, d, "How the report is made", "Read the verdict events, count them, write one page. Sending it to Teams or email comes later (Tier 8).")}
<h2>What's on it</h2>
{table(["Section", "What it shows", "Why it's honest"], [
    ["Rules", "Per rule: pass, fail, nothing to check, could not judge; the fail rate; the change from the week before", "The fail rate counts only conversations actually judged. Nothing to check and could-not-judge are never passes."],
    ["Saved questions", "The six questions' answers, with the conversation, day and rule", "The same definition as the App Insights queries and the chat (" + link("arch-outputs", "saved questions") + ")"],
    ["Requirements broken", "Which spec requirements failed, and how often", "A failure whose rule names no requirement is counted apart, as a gap in the rules file"],
    ["Test data", "A warning when test conversations are counted", "Test verdicts are marked synthetic and left out unless asked for"],
])}
<h2>This week's report for FNOL</h2>
<div class="text"><p>Built today from App Insights. Today FNOL's verdicts are all from test
scenarios, so the warning is on. The one under-escalation is the deliberate demo verdict.</p></div>
<figure><iframe src="{REPORT}" title="FNOL weekly report" style="width:100%;height:900px;border:0;background:#fff"></iframe>
<figcaption><a href="{REPORT}">Open the report on its own page</a></figcaption></figure>
{note("Three things the first build got wrong, fixed before you saw it", "<ol><li>It mixed two batches of verdicts written in different formats on the same afternoon. Every verdict now carries <code>evalharness.schema</code>, a format version, so old and new can be told apart; and a period can start after a format change (<code>--start</code>).</li><li>With <code>--start</code>, it compared against an unfair “week before” made of the old batch. A chosen period is now compared with nothing.</li><li>It said “no requirement was broken” while a rule had failed: that rule simply named no requirement. It now says so, and counts such failures apart.</li></ol>")}
{yaml_block('''.venv/bin/python scripts/weekly_report.py \\
    --resource-group <group> --workspace-name <workspace> \\
    --agent claims-fnol --out report.html        # real customers only
    # --include-synthetic to count test conversations too''', "Run it")}
{code("src/evalharness/report.py", r"^def weekly", r"^def to_html", "The counting, in real code")}
{review("trace-report", "The weekly report", [
    "Is this what an ops lead should see first on a Monday? What would you add, move or remove?",
])}
"""
