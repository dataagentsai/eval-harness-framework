"""Start: what the framework is, why it exists, the whole picture."""

from kit import arrow, box, fig, note, num, table, text
from reg import link, page, review, status


@page("index", "Checking what an AI agent did", None,
      "What this framework is, in one picture.", short="Start here")
def index():
    pic = "".join([
        box(20, 60, 190, 90, "Your agent", ["talks to customers,", "calls tools"], "bx"),
        arrow(210, 105, 280, 105, "writes", ly=95),
        box(280, 60, 190, 90, "Traces", ["what happened, step", "by step (it already", "writes these)"], "bxm"),
        arrow(470, 105, 540, 105, "we read", ly=95),
        box(540, 40, 220, 130, "evalharness", ["rebuilds each", "conversation, runs", "the checks you", "wrote in YAML"], "solid",
            href="session.html", tag="start here"),
        arrow(760, 105, 830, 105),
        box(830, 60, 190, 90, "Results", ["pass / fail + why,", "back into tools", "you already use"], "bxs"),
        text(540, 215, "Checks come from: our five patterns, plus Presidio, Azure, DeepEval, Ragas…", "sm"),
    ])
    return f"""
<div class="text">
<p>An AI agent can write a perfect, polite reply and still be wrong: it can say
“your refund has been issued” when no refund was issued, or pay a claim nobody
looked up. Reading every conversation by hand doesn't scale. This framework
reads what the agent did and checks it against the rules you wrote down.</p>
</div>
{fig(1040, 230, pic, "The whole idea in one picture",
     "The agent already records what it does (traces). We read those, rebuild each conversation, run your checks, and write the verdicts back where your team already looks.")}
{note("How to use this tutorial", "<p>Read the tabs left to right. Each section teaches first and then shows the code. Pages that need your opinion end in a yellow “Your review” box. The " + link("review", "Your review") + " tab collects every question in one place.</p>")}
<h2>Where things stand</h2>
{table(["Part", "What it does", "State"], [
    ["Sessions", "One conversation as an ordered list of steps", status(True)],
    ["Five patterns", "Reusable rules about a whole conversation, filled in with YAML", status(True, "run on FNOL (29 scenarios) and the clothing agent (49)")],
    ["Provider checks", "Presidio, Azure groundedness, DeepEval, Ragas behind one shape", status(True)],
    ["Reading traces", "Rebuild conversations from standard OpenTelemetry traces", status(True, "from a trace file; Phoenix next")],
    ["Blocking inline", "Stop a bad reply before the customer sees it", status(False)],
    ["Cost rules", "The 36 LLM cost rules (LLM-01 to LLM-36)", status(False, "6 exist in llm-cost-explainer")],
    ["Writing results back", "Scores into Langfuse, App Insights, Prometheus", status(False)],
])}
<p class="deeper">The full plan, with every tier and decision, is <code>docs/PLAN.html</code> in the repo.</p>
"""


@page("why", "Why check an agent at all?", "index",
      "Three kinds of mistakes, and which kind of check catches each.", short="Why check?")
def why():
    pic = "".join([
        box(20, 20, 300, 120, "1 · One reply", ["Does this answer leak a", "phone number? Is it based", "on the documents?"], "bx"),
        box(360, 20, 300, 120, "2 · One conversation", ["Did it look the claim up", "before paying it? Did it", "do what it said it did?"], "solid"),
        box(700, 20, 300, 120, "3 · Many conversations", ["Is cost per conversation", "creeping up? Same question", "asked 500 times?"], "bxs"),
        text(170, 170, "provider checks (Presidio, Azure…)", "sm", "middle"),
        text(510, 170, "our five patterns  ← this tutorial", "sm", "middle"),
        text(850, 170, "cost rules (not built yet)", "sm", "middle"),
    ])
    return f"""
<div class="text">
<p>Mistakes come in three sizes, and each needs a different kind of check.</p>
</div>
{fig(1020, 190, pic, "Three sizes of mistake", "Most tools on the market check size 1. Size 2 is where ops teams' real questions live, and it's what the five patterns are for.")}
<div class="text">
<ol>
<li><b>One reply.</b> You can judge it by looking at that reply alone. Many tools already do this well; we plug them in rather than rewrite them.</li>
<li><b>One conversation.</b> You can't judge a payout from the reply. You need the order of events: was the claim read first, did the payout succeed, was a person asked when the amount was large. These are questions like “a cancel happened with no order lookup before it”. They need the whole conversation, in order. That's a <b>session</b>.</li>
<li><b>Many conversations.</b> Some problems only show across days or thousands of calls, such as cost creeping up. These run on a separate engine later.</li>
</ol>
<p>Two more ideas run through everything:</p>
<ul>
<li><b>Write the rules from the agent's spec, never from guesses.</b> When we guessed FNOL's tool names, every check was wrong. When we wrote them from the spec, they were right.</li>
<li><b>Same answer every run.</b> The five patterns are plain code, with no AI model judging. A rule that says “the payout needs a lookup first” gives the same verdict every time, so you can trust a fail.</li>
</ul>
</div>
"""


@page("picture", "The whole picture, one step at a time", "index",
      "Five steps from what the agent did to a verdict you can act on.", short="The whole picture")
def picture():
    steps = [("Read", "Get what the agent did: from a trace file, Phoenix, Langfuse or App Insights.", True),
             ("Rebuild", "Turn the raw records into one Session per conversation.", True),
             ("Plan", "Read your YAML: which checks, with which settings.", True),
             ("Check", "Run each check on each session. Each check answers in the same result shape.", True),
             ("Decide and record", "Turn results into an action (block, alert), write them back, send a weekly report.", False)]
    body = []
    for i, (name, words, built) in enumerate(steps):
        x = 20 + i * 200
        body.append(box(x, 40, 170, 150, name, [w for w in _wrap(words, 20)], "solid" if built else "bxm"))
        body.append(num(x + 14, 40, i + 1))
        if i < len(steps) - 1:
            body.append(arrow(x + 170, 115, x + 200, 115))
    body.append(text(20, 225, "Solid boxes are built. The dashed one is not built yet.", "sm"))
    return f"""
{fig(1020, 240, "".join(body), "Five steps", "The framework is these five steps. Each step talks to the next through a fixed shape, so any piece can be swapped.")}
<div class="text">
<p><b>Why the steps are separate.</b> Each step meets the next through a fixed shape (a <i>port</i>). A Phoenix reader and an App Insights reader both produce the same Session, so the checks never know where the data came from. A Presidio check and one of our patterns both answer with the same result, so the reports never know who judged. Swapping a tool means adding one adapter and changing one line of YAML.</p>
<p><b>Why “decide” is its own step.</b> A check only says what it found. Whether that blocks a reply, raises an alert or is just counted is a separate choice, so the same check can block in one company and only alert in another.</p>
<p><b>We never replace a team's tools.</b> No database, dashboard or chat UI of our own: we read from where traces already are and write verdicts back there.</p>
</div>
{review("picture", "The whole picture", [
    ("Is the five-step picture clear enough to explain to an ops person in two minutes? If not, which step is unclear?",
     "Yes. The five steps stay the explanation."),
    ("Is anything missing that an ops team would expect, such as a weekly report or alerts?",
     "Yes: a weekly report and alerts. Both belong to step 5 (decide and record), now drawn there as not built yet."),
])}
"""


def _wrap(s, n):
    out, cur = [], ""
    for w in s.split():
        if len(cur) + len(w) + 1 > n and cur:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return out + [cur]
