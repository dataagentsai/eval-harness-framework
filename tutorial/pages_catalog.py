"""Catalog: every common check, sorted into any agent, by kind of agent, and
domain-specific, with what checks each one here today."""

from collections import defaultdict
from html import escape

import sources
from kit import box, fig, note, table, text
from reg import link, page, review, status


def _by(oid):
    found = sources.checked_by().get(oid)
    return ", ".join(f"<code>{k}</code>" for k in found) if found else "—"


@page("catalog", "A catalog of common checks", None,
      "Every common check, sorted: for any agent, by kind of agent, and for one business.", short="Catalog")
def catalog():
    obs = sources.obligations()
    core = [o for o in obs if o["core"]]
    kind = [o for o in obs if not o["core"]]
    cost = sources.cost_rules()
    sig = sources.detection_patterns()
    covered = sources.checked_by()
    agents = [sources.agent_trace(a) for a in sources.AGENTS]
    domain_rules = sum(len(r) for r, _ in agents)
    layers = "".join([
        box(20, 30, 340, 190, "Any agent", [f"{len(core)} core obligations", f"{len(cost)} cost rules",
                                            f"{len(sig)} warning signs", "same everywhere"], "solid", href="cat-any.html", tag="open"),
        box(390, 30, 340, 190, "By kind of agent", [f"{len(kind)} obligations across", "10 kinds: RAG, tool-using agent,",
                                                    "multi-agent, chat assistant…", "depends on how it's built"], "bx",
            href="cat-kind.html", tag="open"),
        box(760, 30, 340, 190, "For one business", ["5 pattern shapes, filled with", "the business's own rules",
                                                    f"{domain_rules} rules for 2 agents so far", "depends on the domain"], "bxs",
            href="cat-domain.html", tag="open"),
        text(20, 250, "← domain-agnostic: written once, apply to every agent", "sm"),
        text(1100, 250, "domain-specific: written per business →", "sm", "end"),
    ])
    return f"""
<div class="text">
<p>You asked whether there's a corpus of common checks, sorted into domain-agnostic
and domain-specific. There is now: this section. It isn't typed in. It is read
from the sources that already hold the checks, when the pages are built:</p>
<ul>
<li><b>The AI Assurance Catalog</b> (our open standard): {len(obs)} obligations, things that
must be true of an AI system. {len(core)} apply to every AI system; {len(kind)} apply to a kind of system.</li>
<li><b>The LLM cost rules</b>: {len(cost)} ways money is wasted on model calls.</li>
<li><b>Warning signs</b> (the catalog's detection patterns): {len(sig)} symptoms seen in real traces, each linked to the obligations that catch it.</li>
<li><b>Our five patterns</b>, filled in with each business's rules from its spec.</li>
</ul>
</div>
{fig(1120, 270, layers, "Three layers of checks", "From most general to most specific. Click a layer to see every check in it.")}
<h2>How much of it we check today</h2>
{table(["Layer", "In the catalog", "Checked by this framework today"], [
    ["Any agent: obligations", len(core), sum(1 for o in core if o["id"] in covered)],
    ["Any agent: cost rules", len(cost), f"{sum(1 for c in cost if c['built'])} (built in llm-cost-explainer; joining here in Tier 5)"],
    ["By kind of agent", len(kind), sum(1 for o in kind if o["id"] in covered)],
    ["For one business (FNOL, clothing)", f"{sum(len(q) for _, q in agents)} requirements in their specs",
     f"{sum(1 for _, q in agents for x in q if x['rules'])} tested by {domain_rules} rules"],
])}
{note("Read the gaps honestly", "<p>Most obligations aren't covered by a check here yet, and that's expected: many are tested before release (golden sets, red-teaming), some belong to the platform (identity, network), and the framework is young. Every “—” on these pages is a known, named gap, not a hidden one.</p>")}
{review("catalog", "The catalog", [
    ("Is “any agent / by kind of agent / for one business” the right way to sort checks for a client conversation?",
     "Yes, keep the three layers."),
    ("Which gaps should we close first: the core obligations, the cost rules, or more domain requirements?",
     "Domain requirements first (that's what a client pays for), then the cost rules (Tier 5), then the core obligations that can be checked after the fact."),
])}
"""


@page("cat-any", "Checks for any agent", "catalog",
      "Core obligations, cost rules and warning signs: domain-agnostic.", short="Any agent")
def cat_any():
    core = [o for o in sources.obligations() if o["core"]]
    groups = defaultdict(list)
    for o in core:
        groups[o["dimension"]].append(o)
    parts = []
    for dim in sorted(groups):
        rows = [[o["id"], o["level"], escape(o["title"]), _by(o["id"])] for o in groups[dim]]
        parts.append(f"<h3>{dim.capitalize()}</h3>" + table(["Id", "Level", "Must be true", "Checked here by"], rows))
    cost = sources.cost_rules()
    sig = [s for s in sources.detection_patterns()]
    return f"""
<div class="text"><p>These apply whatever the business: a support bot, a claims agent, a code
assistant. <b>MUST</b> means required, <b>SHOULD</b> recommended, <b>MAY</b> optional.</p></div>
<h2>{len(core)} core obligations, by concern</h2>
{''.join(parts)}
<h2>{len(cost)} cost rules</h2>
{table(["Id", "The waste it finds", "State"], [[c["id"], escape(c["title"]), status(c["built"], "in llm-cost-explainer" if c["built"] else "")] for c in cost])}
<h2>{len(sig)} warning signs</h2>
<div class="text"><p>Symptoms you can spot in traces, each linked to the obligations that catch it.
They're grouped by where they show up: the agent's behaviour, cost, or operations.</p></div>
{table(["Id", "Area", "Warning sign", "Caught by"], [[s["id"], s["domain"], escape(s["name"]), ", ".join(s["caught_by"]) or "—"] for s in sig])}
"""


@page("cat-kind", "Checks by kind of agent", "catalog",
      "Obligations that depend on how the system is built: RAG, tools, multi-agent…", short="By kind of agent")
def cat_kind():
    arche = sources.archetypes()
    kind = [o for o in sources.obligations() if not o["core"]]
    parts = []
    for aid, a in arche.items():
        mine = [o for o in kind if aid in o["archetypes"]]
        if not mine:
            continue
        rows = [[o["id"], o["level"], escape(o["title"]), _by(o["id"])] for o in mine]
        parts.append(f"<h3>{aid} · {escape(a['name'])}</h3><p class=\"deeper\">{escape(' '.join(str(a.get('summary', '')).split()))}</p>"
                     + table(["Id", "Level", "Must be true", "Checked here by"], rows))
    return f"""
<div class="text"><p>These depend on <i>how</i> the system is built, not on the business. A
retrieval-based answerer must cite real sources; a tool-using agent must stop when
it's going round in circles. An obligation can belong to several kinds, so it may
appear more than once. FNOL and the clothing agent are both <b>A4</b> (conversational)
and <b>A6</b> (tool-using).</p></div>
{''.join(parts)}
"""


@page("cat-domain", "Checks for one business", "catalog",
      "The five pattern shapes, filled in with each business's own rules.", short="For one business")
def cat_domain():
    shapes = [("requires_before", "Do A before B", "pay after reading the claim; cancel after reading the order"),
              ("argument_limit", "A number within a limit", "refund at most ₹10,000"),
              ("claim_needs_action", "Don't say it unless it happened", "“has been paid” only after a payout"),
              ("decision_vs_should", "Decide when the rules say", "approval above ₹25,000; hand over when someone was hurt"),
              ("consistency", "Facts come from a system", "claim ids and amounts from a tool")]
    parts = []
    for agent in sources.AGENTS:
        rules, _ = sources.agent_trace(agent)
        rows = [[f"<code>{r['name']}</code>", f"<code>{r['kind']}</code>", escape(r["description"]) or "—",
                 ", ".join(f"<code>{x}</code>" for x in r["requirements"]) or "—"] for r in rules]
        parts.append(f"<h3>{agent['name']}</h3>" + table(["Rule", "Shape", "In plain words", "Requirements it tests"], rows))
    return f"""
<div class="text"><p>Business rules differ per company, but their <b>shapes</b> repeat. We write
the five shapes once; a business fills them in with YAML from its own spec. So the
domain-specific layer is two things: the shapes (shared) and each business's
rules (theirs).</p></div>
{table(["Shape", "In plain words", "Example"], [[link("p-" + k.replace("_", "-"), f"<code>{k}</code>"), w, e] for k, w, e in shapes])}
<h2>The rules written so far</h2>
{''.join(parts)}
{note("What's missing", "<p>Two businesses so far, both customer support. A library of common rules per industry (banking, insurance, retail, healthcare) would come from real specs, one at a time, not from guesses. That's the lesson from FNOL: rules guessed without the spec were wrong everywhere.</p>")}
<p class="deeper">Which requirement each rule tests, and which requirements nothing tests yet: {link("requirements", "Requirements")}.</p>
"""
