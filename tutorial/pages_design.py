"""Design: the ideas the code is built on, the core classes, and every
decision taken (read from PLAN.html)."""

import sources
from kit import box, fig, path, table, text
from pages_session import code
from reg import link, page


@page("design", "Design: the ideas the code is built on", None,
      "Eight ideas, the class diagram, and the adapter in real code.", short="Design")
def design():
    classes = "".join([
        box(20, 20, 300, 200, "EvalRequest", ["query, messages", "response (+ tool calls, results)",
                                              "context passages · expected", "session · meta"], "bx"),
        box(410, 20, 300, 200, "Adapter (a check)", ["to_provider(request)", "call(payload)  ← only part", "      that touches the vendor",
                                                     "from_provider(raw) → result", "obligations · requirements"], "solid"),
        box(800, 20, 300, 200, "EvalResult", ["verdict: pass·fail·skip·error", "score 0–1 · raw_score · threshold",
                                              "reason · cost · latency", "raw · findings · dropped"], "bx"),
        path("M320 120 L410 120"), path("M710 120 L800 120"),
        text(365, 110, "in", "sm", "middle"), text(755, 110, "out", "sm", "middle"),
        box(20, 270, 300, 120, "Session", ["steps in order", "(see Sessions)"], "bxm", href="session.html", tag="open"),
        box(410, 270, 300, 120, "Scale", ["the provider's min, max,", "direction, threshold → 0–1"], "bxm"),
        box(800, 270, 300, 120, "Finding", ["kind · confidence · severity", "where in the text"], "bxm"),
        path("M170 270 L170 220", "lnd"), path("M560 270 L560 220", "lnd"), path("M950 270 L950 220", "lnd"),
    ])
    ideas = [
        ("One request shape, one result shape", "Every check, ours or a vendor's, is handed the same <code>EvalRequest</code> and answers with the same <code>EvalResult</code>. Reports never care who judged.", "The spike ran four providers through one shape and it held."),
        ("Ports and adapters", "The engine talks to fixed shapes (ports); each tool fits one through an adapter chosen in YAML.", "The same rules must run on the open stack, Azure, and later AWS or GCP."),
        ("Three parts per adapter", "Translate in, call, translate out. Only the middle part imports the vendor's SDK.", "Vendor SDKs change monthly; the change stays in one small function, and recorded answers test the other two."),
        ("One scale", "Every score becomes 0–1 with 1 best, from the provider's own range and threshold set in YAML.", "Azure scores 1–5, others 0–1, some lower-is-better. Mixing them honestly needs one scale."),
        ("Say what was lost", "A result lists what didn't fit into the provider's shape (<code>dropped</code>) and keeps the provider's raw answer.", "A lossy result must be labelled, not trusted silently."),
        ("Confidence is not severity", "How sure a provider is and how bad a finding is are separate numbers.", "Presidio is surer of a date than of a URL, yet an email leak is worse than either."),
        ("Checking is separate from deciding", "A check says what it found; a policy step decides block, alert or count.", "The same check can block in one company and only alert in another."),
        ("Rules are data, linked to requirements", "Rules are YAML; each names the requirements it tests and each check the standard's obligations.", "Every fail says which promise broke; a test catches a broken link."),
    ]
    return f"""
<div class="text"><p>Eight ideas run through the code. Each one is here with the reason for it;
the {link("design-decisions", "decisions")} page lists every choice taken so far.</p></div>
{table(["Idea", "What it means", "Why"], [[f"<b>{a}</b>", b, c] for a, b, c in ideas])}
<h2>The core classes</h2>
{fig(1120, 410, classes, "Class diagram", "A request goes into an adapter and a result comes out. Every check, ours or a vendor's, has this shape.")}
<h2>The adapter, in real code</h2>
{code("src/evalharness/adapter.py", r"^class Adapter", r"    def dropped", "The three parts, plus what every check declares")}
<div class="text"><p>Where these classes sit in the whole system: {link("arch-engine", "inside the engine")}.</p></div>
"""


@page("design-decisions", "Every decision taken so far", "design",
      "Read from PLAN.html: what was decided, and why.", short="Decisions")
def design_decisions():
    rows = [[t, d, w, when] for t, d, w, when in sources.decisions()]
    return f"""
<div class="text"><p>{len(rows)} decisions, read from <code>docs/PLAN.html</code> when this page was built,
so it is always the plan's own list. To reopen one, say its number.</p></div>
{table(["#", "Decision", "Why", "When"], rows)}
"""
