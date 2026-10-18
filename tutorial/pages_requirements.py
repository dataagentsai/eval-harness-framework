"""Requirements: what must be true, where it's written, and which rule tests it."""

from html import escape

import sources
from kit import arrow, box, fig, note, table
from pages_session import yaml_block
from reg import link, page, review


@page("requirements", "Requirements: what must be true", None,
      "Where requirements come from, and how each rule is linked to the ones it tests.", short="Requirements")
def requirements():
    chain = "".join([
        box(20, 40, 250, 130, "Requirement", ["P-PAYOUT: “an amount above", "₹25,000 needs a claims", "handler”"], "bxs"),
        arrow(270, 105, 320, 105, "tested by", ly=95),
        box(320, 40, 250, 130, "Rule (YAML)", ["payout_approval", "requirements: [P-PAYOUT]"], "bx",
            href="yaml.html", tag="the file"),
        arrow(570, 105, 620, 105, "uses", ly=95),
        box(620, 40, 230, 130, "Check", ["decision_vs_should", "helps meet AAC-0078", "(the standard)"], "solid",
            href="p-decision-vs-should.html", tag="the pattern"),
        arrow(850, 105, 900, 105, "gives", ly=95),
        box(900, 40, 200, 130, "Result", ["fail: no approval", "for ₹61,000", "→ P-PAYOUT"], "bx"),
    ])
    rows = []
    for agent in sources.AGENTS:
        _, reqs = sources.agent_trace(agent)
        tested = sum(1 for r in reqs if r["rules"])
        rows.append([link(f"req-{agent['id']}", agent["name"]), len(reqs), tested,
                     f"{100 * tested // max(len(reqs), 1)}%"])
    return f"""
<div class="text">
<p>A <b>requirement</b> is one thing that must be true of the agent, written down
before anyone builds or checks it. Without requirements, a check is just an
opinion. With them, every fail says <i>which promise</i> was broken.</p>
<p>Requirements come from two places:</p>
<ul>
<li><b>The agent's spec</b>: what this business needs. FNOL's spec says “an amount
above ₹25,000 needs a claims handler” and gives it the id <code>P-PAYOUT</code>. These are
domain-specific.</li>
<li><b>The standard</b> (the AI Assurance Catalog): what every AI system of a kind
must do, such as <code>AAC-0110</code>, “a claimed action is supported by that action's
result”. These are domain-agnostic; see {link("catalog", "the catalog")}.</li>
</ul>
</div>
{fig(1120, 200, chain, "From requirement to result", "Each link is data, not a comment: the rule names its requirement ids, and the check declares the standard's obligations it helps meet.")}
<h2>How the link is written</h2>
{yaml_block('''spec: clean-ai-engineering/drafts/examples/motor-claims-fnol.aoas.yaml

evaluators:
  payout_approval:
    description: A person approves exactly the payouts over ₹25,000.
    requirements: [P-PAYOUT, issue_payout.authority.agent_when]
    adapter: decision_vs_should
    ...''', "examples/claims-fnol.yaml (part)")}
<div class="text"><p><b>Kept honest by a test.</b> If a rule names a requirement id that isn't in the
spec (a typo, or a requirement that was renamed), the test suite fails. The
wording on these pages is looked up in the spec when they're built, so it can't drift.</p></div>
<h2>Coverage: how many requirements a rule tests</h2>
{table(["Agent", "Requirements in its spec", "Tested by a rule", "Share"], rows)}
{note("Why coverage is low, and why that's fine for now", "<p>Many requirements are about what the agent's systems refuse (the claims system won't register a claim on a lapsed policy), and are tested in the agent's own scenarios, not after the fact. Others need checks we haven't built (a date promised in a reply). Each untested requirement is listed by name on the agent's page, so the gap is known and owned.</p>")}
{review("requirements", "Requirements", [
    ("Should every rule be required to name at least one requirement, so no rule exists without a reason?",
     "Yes, as a warning rather than a refusal until a team has a spec. FNOL and the clothing agent already comply."),
    ("Which untested FNOL requirements matter most to check after the fact?",
     "P-PAYOUT-OWED (pay when asked; a status question issues nothing), P-OWN-WORDS (act only on a named claim), P-OWNERSHIP, and the “never a date” half of P-CLAIM-STATUS."),
])}
"""


def _agent_page(agent):
    def render():
        rules, reqs = sources.agent_trace(agent)
        tested = [r for r in reqs if r["rules"]]
        untested = [r for r in reqs if not r["rules"]]

        def rows(items):
            return [[f"<code>{escape(r['id'])}</code>", escape(str(r["text"])), escape(r["concern"]),
                     ", ".join(f"<code>{x}</code>" for x in r["rules"]) or "—"] for r in items]
        return f"""
<div class="text"><p>Every requirement in the {escape(agent['name'])}'s spec, read from the spec
when this page was built, with the rules in <code>examples/{agent['example']}</code> that test it.
{len(tested)} of {len(reqs)} are tested.</p></div>
<h2>Tested ({len(tested)})</h2>
{table(["Id", "Requirement", "Concern", "Tested by"], rows(tested))}
<h2>Not tested yet ({len(untested)})</h2>
{table(["Id", "Requirement", "Concern", "Tested by"], rows(untested))}
<h2>The rules, and the standard they also serve</h2>
{table(["Rule", "Shape", "Requirements", "Standard obligations"], [[f"<code>{r['name']}</code>", f"<code>{r['kind']}</code>", ", ".join(r["requirements"]) or "—", ", ".join(r["obligations"]) or "—"] for r in rules])}
"""
    return render


for _a in sources.AGENTS:
    page(f"req-{_a['id']}", f"{_a['name']}: requirements and their rules", "requirements",
         "Every requirement in its spec, tested or not.", short=_a["name"])(_agent_page(_a))


@page("req-standard", "The standard's obligations our checks serve", "requirements",
      "Which AI Assurance Catalog obligations each built check helps meet.", short="The standard")
def req_standard():
    obs = {o["id"]: o for o in sources.obligations()}
    rows = [[oid, escape(obs[oid]["title"]) if oid in obs else "?",
             "core" if obs.get(oid, {}).get("core") else ", ".join(obs.get(oid, {}).get("archetypes", [])),
             ", ".join(f"<code>{k}</code>" for k in ks)] for oid, ks in sorted(sources.checked_by().items())]
    return f"""
<div class="text"><p>Each built check declares, in its code, which obligations of the standard it
helps meet. “Helps” matters: an obligation is met by a whole practice (a test set, a
gate, monitoring), and our check is one piece of the evidence.</p></div>
{table(["Obligation", "Must be true", "Applies to", "Checks that help"], rows)}
<div class="text"><p><code>requires_before</code> and <code>argument_limit</code> declare none: they test
the business's own rules, so their requirements come only from the agent's spec.</p></div>
"""
