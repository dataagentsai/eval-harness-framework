"""Architecture: where the framework fits, what it plugs into, where checks
run (offline, inline, online), and the engine's ports."""

from html import escape

import sources
from kit import arrow, box, fig, note, num, path, table, text
from reg import link, page, review, status


@page("arch", "Where the framework fits", None,
      "The big picture: your agent, its traces, our engine, and the tools around it.", short="Architecture")
def arch():
    d = "".join([
        # your application
        '<rect class="zone" x="10" y="16" width="1100" height="214" rx="16"/>',
        text(24, 40, "YOUR AI APPLICATION (unchanged)", "lbl"),
        box(30, 80, 130, 80, "Customer", ["types a message"], "bx"),
        arrow(160, 120, 210, 120),
        box(210, 60, 200, 120, "Your agent", ["Pydantic AI · LangGraph", "Agent SDK · own code"], "bx"),
        arrow(410, 100, 470, 100),
        box(470, 60, 180, 80, "Gateway", ["LiteLLM · Azure APIM"], "bxm"),
        arrow(650, 100, 710, 100),
        box(710, 60, 170, 80, "Models", ["OpenAI · Azure · Groq"], "bx"),
        arrow(410, 160, 470, 170),
        box(470, 150, 180, 66, "Tools / systems", ["orders, claims, CRM"], "bx"),
        box(910, 60, 185, 156, "Instrumentors", ["OpenTelemetry SDK,", "OpenInference,", "the framework's own", "tracing"], "bxm"),
        # the engine
        box(330, 300, 440, 160, "evalharness", ["read · rebuild sessions · plan (YAML)", "check · decide · record",
                                                "one request shape, one result shape"], "solid", href="arch-engine.html",
            tag="inside"),
        # inline, from the agent and the gateway
        path("M300 180 L300 240 L420 240 L420 300"), num(300, 262, 1),
        text(318, 268, "inline", "sm"),
        path("M560 140 L560 300", "lnd"), num(560, 262, 2),
        text(578, 268, "gateway", "sm"),
        # traces
        box(20, 300, 240, 160, "Where traces land", ["Phoenix · Langfuse", "App Insights · LangSmith", "OTLP files"], "bxs"),
        path("M1000 216 L1000 250 L140 250 L140 300"),
        text(820, 244, "writes traces", "sm"),
        arrow(260, 380, 330, 380), num(295, 352, 3),
        text(295, 412, "online", "sm", "middle"),
        # checks we call
        box(850, 300, 255, 160, "Checks we call", ["Presidio · Azure AI Evaluation", "DeepEval · Ragas", "Content Safety · Prompt Guard",
                                                     "judge models · our patterns"], "bx", href="arch-integrations.html",
            tag="all tools"),
        arrow(770, 380, 850, 380, "calls", ly=370),
        # offline
        box(20, 530, 300, 130, "Before release and in batch", ["golden datasets · CI release gate", "backfill on old traces",
                                                              "cost rules over days"], "bxm"),
        path("M320 595 L400 595 L400 460"), num(400, 500, 4),
        text(420, 504, "offline", "sm"),
        # results out
        arrow(600, 460, 600, 530, "writes results", lx=660, ly=500),
        box(470, 530, 300, 130, "Your tools, not ours", ["Langfuse / Phoenix scores", "App Insights · Prometheus + Grafana",
                                                         "Teams · ServiceNow alerts"], "bxs"),
        box(810, 530, 295, 130, "Content we ship", ["dashboard templates", "alert rules (KQL, PromQL)",
                                                    "metric definitions"], "bxm"),
        path("M810 595 L770 595", "lnd"),
    ])
    return f"""
<div class="text">
<p>This is what we're trying to do, in one drawing. Your agent and the tools
around it stay as they are. The framework (the dark box) plugs in at four
points, numbered below, and writes its verdicts back into tools your team
already uses. It has no database, dashboard or chat window of its own.</p>
</div>
{fig(1120, 680, d, "Where the eval harness framework fits",
     "The numbered circles are where checks plug in: (1) inside the agent, (2) at the gateway, (3) on the traces afterwards, (4) before release or in batch. Dashed boxes are optional.")}
<h2>The four ways in, in plain words</h2>
{table(["#", "Where", "When", "Can it stop a bad reply?"], [
    ["1", "Hooks inside the agent's framework", "During the turn: " + link("arch-modes", "inline"), "Yes"],
    ["2", "The gateway every model call passes through", "During the turn: inline", "Yes, for model calls only"],
    ["3", "The traces the agent already writes", "After the turn: " + link("arch-modes", "online"), "No: it alerts and reports"],
    ["4", "Golden test sets, CI, history", "Before release or in batch: " + link("arch-modes", "offline"), "It stops a release, not a reply"],
])}
{note("What's built today", "<p>The engine's check step, the five patterns, four provider checks, and reading traces from a trace file (way 3). The reference agent's own harness already runs checks inline (way 1) using this package. Running <i>any</i> check at the gateway, inline in other frameworks, and writing results back are planned: see " + link("arch-integrations", "every integration") + ".</p>")}
{review("arch", "The big picture", [
    ("Does this drawing show what we're trying to do? What would you add or remove before showing it to a client?",
     "Yes. For a client, drop the tier labels and keep the four ways in."),
])}
"""


@page("arch-modes", "When checks run: offline, inline, online", "arch",
      "Three timings, what each can do, and every point a check plugs in.", short="Offline, inline, online")
def arch_modes():
    turn_y = 235
    d = [
        '<rect class="zone" x="10" y="14" width="1100" height="118" rx="14"/>',
        text(24, 36, "OFFLINE · before release, or in batch", "lbl"),
        box(30, 52, 200, 64, "Golden test set", ["known questions + answers"], "bxm"),
        arrow(230, 84, 270, 84),
        box(270, 52, 230, 64, "Release gate in CI", ["a fail blocks the merge"], "bxm"),
        box(540, 52, 260, 64, "Backfill and scheduled re-runs", ["new rules on old traces"], "bxm"),
        box(840, 52, 255, 64, "Cost rules over days", ["many calls, not one"], "bxm"),
        '<rect class="zone" x="10" y="150" width="1100" height="240" rx="14"/>',
        text(24, 172, "INLINE · during the turn, before the customer sees anything", "lbl"),
        box(20, turn_y, 130, 64, "Customer", ["sends a message"], "bx"),
        box(250, turn_y, 140, 64, "Model call", ["decides what to do"], "bx"),
        box(520, turn_y, 140, 64, "Tool runs", ["e.g. issue_refund"], "bx"),
        box(780, turn_y, 140, 64, "Model call", ["writes the reply"], "bx"),
        box(990, turn_y, 110, 64, "Customer", ["reads it"], "bx"),
        arrow(150, 267, 250, 267), arrow(390, 267, 520, 267), arrow(660, 267, 780, 267), arrow(920, 267, 990, 267),
        box(250, 336, 670, 40, "or at the gateway (LiteLLM, APIM): it sees every model call", [], "bxm"),
    ]
    marks = [(200, "pre_model", "what goes to the model"), (430, "post_model", "what the model asked for"),
             (480, "pre_tool", "before a tool acts"), (720, "post_tool", "what the tool returned"),
             (955, "reply", "the reply itself")]
    for i, (x, name, what) in enumerate(marks):
        up = i % 2 == 0
        d.append(f'<circle class="nm" cx="{x}" cy="267" r="13"/>')
        d.append(f'<text class="nmt" x="{x}" y="273" text-anchor="middle">{i + 1}</text>')
        d.append(text(x, 222 if up else 322, name, "mn", "middle"))
        if up:
            d.append(text(x, 205, what, "sm", "middle"))
    d += [
        '<rect class="zone" x="10" y="410" width="1100" height="150" rx="14"/>',
        text(24, 432, "ONLINE · after the turn, on live traffic", "lbl"),
        box(30, 450, 210, 80, "Trace written", ["by the agent's own tracing"], "bx"),
        arrow(240, 490, 290, 490),
        box(290, 450, 220, 80, "Where traces land", ["Phoenix, Langfuse, App Insights"], "bxs"),
        arrow(510, 490, 560, 490), text(535, 548, "pull or tap", "sm", "middle"),
        box(560, 442, 280, 96, "Eval worker", ["a sample of traffic; session rules", "when a conversation ends"], "solid"),
        arrow(840, 490, 890, 490),
        box(890, 450, 210, 80, "Scores and alerts", ["into your tools"], "bxs"),
    ]
    rows = [[f"<code>{c['kind']}</code>", c["provider"], c["speed"], f"{c['ms']:g} ms"] for c in sources.checks()]
    return f"""
<div class="text">
<p>The same check can run at three different times. Which one you pick decides
what the check can do about a problem.</p>
<ul>
<li><b>Inline</b> runs <i>during</i> the turn, before the customer sees anything. It can block,
redact or hand over. It must be fast, because the customer is waiting.</li>
<li><b>Online</b> runs <i>after</i> the turn, on real traffic, usually a sample. It can't undo a
reply, but it can alert, open a review and spot trends. It can take seconds, so
AI judges are fine here.</li>
<li><b>Offline</b> runs <i>before release</i> or in batch: on golden test sets in CI (a fail blocks
the release), re-running new rules over old traces, and cost rules that need days of data.</li>
</ul>
</div>
{fig(1120, 575, "".join(d), "Offline, inline and online, with every injection point",
     "The five numbered points are the inline moments; each can also be reached at the gateway for model calls. Online and offline read what the agent already recorded.")}
{table(["", "Offline", "Inline", "Online"], [
    ["When", "Before release, or in batch", "During the turn", "Seconds to minutes after the turn"],
    ["Can it stop a bad reply?", "No; it stops a bad <i>release</i>", "Yes: block, redact, hand over", "No; it alerts and opens a review"],
    ["Time it may take", "Minutes to hours", "Milliseconds", "Seconds"],
    ["What it reads", "Golden sets, months of traces, cost records", "The request at that moment", "Traces and whole sessions"],
    ["Good for", "Regression, cost rules, backfill", "PII, injection, argument limits, spend caps", "The five patterns, groundedness, judged checks"],
    ["Built here", status(False, "release CLI: Tier 7; cost rules: Tier 5"),
     status(False, "any check at any moment: Tier 3 (the reference agent's harness already does it its own way)"),
     status(True, "from a trace file; stores next")],
])}
<h2>Each check declares its speed</h2>
<div class="text"><p>Every check states how fast it is, and the framework refuses to put a slow
check in a fast place. Measured: DeepEval's “deterministic” check takes about 500 ms,
so it's online, not inline; Presidio takes about 2 s on its first call, so an inline host must warm it up.</p></div>
{table(["Check", "Provider", "Speed class", "Expected time"], rows)}
{review("arch-modes", "Offline, inline, online", [
    ("Is the three-timings explanation clear enough for an ops lead deciding where a rule should run?",
     "Yes. The comparison table is the one-slide version."),
])}
"""


@page("arch-integrations", "Every tool we read from, call, or write to", "arch",
      "Open source and cloud tools, upstream and downstream, with what's built.", short="Integrations")
def arch_integrations():
    cols = [("source", "WE READ FROM", "where traces already are"), ("host", "CALLS US INLINE", "hosts and hooks"),
            ("check", "WE CALL", "checks and judges"), ("sink", "WE WRITE TO", "your existing tools")]
    d, height = [], 0
    for c, (side, head, sub) in enumerate(cols):
        x = 20 + c * 275
        d.append(text(x + 125, 30, head, "lbl", "middle"))
        d.append(text(x + 125, 50, sub, "sm", "middle"))
        items = [i for i in sources.INTEGRATIONS if i[0] == side]
        for r, (_, name, family, state) in enumerate(items):
            y = 70 + r * 62
            kind = "solid" if state == "built" else ("bx" if state == "next" else "bxm")
            d.append(box(x, y, 250, 52, name, [f"{sources.FAMILY[family]} · {state}"], kind))
            height = max(height, y + 70)
    d.append(text(20, height + 10, "Dark: built.  Blue: next.  Dashed: planned (tier shown) or later.", "sm"))
    rows = [[escape(name), {"source": "we read from", "host": "calls us inline", "check": "we call",
                            "sink": "we write to"}[side], sources.FAMILY[family],
             status(True) if state == "built" else escape(state)]
            for side, name, family, state in sources.INTEGRATIONS]
    return f"""
<div class="text"><p>Everything the framework touches, in four columns. We never replace any of
these tools: we read from them, call them, or write into them. Each one sits
behind an adapter, so adding a tool is one adapter plus one line of YAML, and
the same rules run whichever tools a client has.</p></div>
{fig(1120, height + 24, "".join(d), "All integrations", "Upstream on the left, downstream on the right. Each box says whose tool it is (open source or a cloud) and its state.")}
{table(["Tool", "How we use it", "Whose", "State"], rows)}
{note("Per cloud, in one line", "<p><b>Open stack:</b> OpenTelemetry, Phoenix or Langfuse, Presidio, an open judge model, Prometheus and Grafana. <b>Azure:</b> App Insights (KQL) in and out, Azure AI Evaluation and Content Safety, Azure OpenAI as the judge. <b>AWS and Google Cloud:</b> CloudWatch, Bedrock Guardrails and Cloud Trace come later, as adapters, when a client needs them.</p>")}
"""


@page("arch-engine", "Inside the engine: ports and adapters", "arch",
      "Nine ports: the fixed shapes every tool plugs into.", short="Inside the engine")
def arch_engine():
    ports = [
        ("TraceSource", "Upstream", "Reads traces or datasets; yields spans to rebuild sessions from", True, "OTLP file built"),
        ("InlineHook", "Host", "Lets a framework, gateway or CI step call our checks at a moment", False, "Tier 7"),
        ("Evaluator", "Called", "One check: request in, result out", True, "8 checks"),
        ("Judge", "Called", "One judge-model setting, handed to each SDK in its own shape", True, ""),
        ("RuleRunner", "Ours", "Runs rules over many records (SQL), reused from llm-cost-explainer", False, "Tier 5"),
        ("StateStore", "Ours", "Running totals: budgets, rates, repeat calls", False, "Tier 3"),
        ("Policy", "Ours", "Turns results into one action: allow, redact, block, escalate, alert", False, "Tier 3"),
        ("ResultSink", "Downstream", "Writes results into the team's tools", False, "Tier 4"),
        ("AlertSink", "Downstream", "Sends alerts when a rule over results fires", False, "Tier 8"),
    ]
    return f"""
<div class="text">
<p>A <b>port</b> is a fixed shape: “give me spans”, “judge this request”, “store
this result”. The engine only ever talks to ports. Each real tool sits behind an
<b>adapter</b> that fits the port, chosen by name in YAML. That's why swapping
Phoenix for App Insights, or Presidio for Azure Content Safety, never touches a
rule or a report.</p>
<p>The engine's five steps are drawn on {link("picture", "the whole picture")}; this page lists
the ports those steps talk through.</p>
</div>
{table(["Port", "Side", "What it does", "State"], [[f"<code>{n}</code>", s, w, status(b, e)] for n, s, w, b, e in ports])}
<div class="text"><p>How a check's adapter is built, and why it has three parts, is on {link("design", "Design")}.</p></div>
"""
