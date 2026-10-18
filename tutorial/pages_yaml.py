"""Writing rules: the FNOL example file, read block by block."""

import live
from kit import note, table
from pages_session import yaml_block
from reg import link, page, review


@page("yaml", "Reading a rules file: FNOL's", None,
      "The real example file, block by block, in plain words.", short="Writing rules")
def yaml_page():
    src = live.fnol_yaml()
    rows = [
        ["<code>preset: customer-support</code>",
         "Start from our ready-made set for support agents: a PII check (Presidio) and a groundedness check.",
         link("presets", "Presets")],
        ["<code>judge:</code>",
         "Which AI model judges the checks that need one. For a client this must be the client's own model; "
         "the file won't start without it.", "—"],
        ["<code>pii: severity: {DATE_TIME: 0.0}</code>",
         "Change one field of a preset check: accident dates are expected in claims, so a date is not a leak.",
         link("presets", "Presets")],
        ["<code>payout_needs_claim_lookup</code>", "Never pay a claim nobody has read.",
         link("p-requires-before", "requires_before")],
        ["<code>payout_approval</code>",
         "A person approves exactly the payouts over ₹25,000. The amount is read from the claim, "
         "because FNOL's payout call has no amount.", link("p-decision-vs-should", "decision_vs_should")],
        ["<code>payout_promise_kept</code>", "Say “has been paid” only after a payout succeeded.",
         link("p-claim-needs-action", "claim_needs_action")],
        ["<code>handed_to_person</code>",
         "Hand over when two tool calls fail in a row, when the customer asks for a person, or when someone was hurt. "
         "<code>check: under</code>: only a <i>missed</i> hand-over is judged, because the file lists 3 of the spec's 10 triggers.",
         link("p-decision-vs-should", "decision_vs_should")],
        ["<code>facts_from_systems</code>", "Claim ids and amounts in a reply must come from a tool.",
         link("p-consistency", "consistency")],
    ]
    return f"""
<div class="text">
<p>This is the whole file a domain team writes. Everything under
<code>evaluators</code> is in FNOL's own words: its real tool names, the claim's
fields, and how a turn ends. Each rule was written from FNOL's spec, then run
on its 29 test scenarios (48 conversations).</p>
</div>
{yaml_block(src, "examples/claims-fnol.yaml")}
<h2>Block by block</h2>
{table(["Block", "In plain words", "Pattern"], rows)}
{note("What running it on real conversations taught us", "<p>The first version guessed FNOL's tool names and was wrong everywhere. Four fixes came from that run: the real names, the <code>result_of</code> and <code>all:</code> conditions, the negation guard, and counting what the customer said as known facts. The rule now: <b>write rules from the spec, never from guesses.</b></p>")}
{review("yaml", "The FNOL rules file", [
    ("Could an ops person write this file without help? Which line would they get stuck on?",
     "Not yet: the regular expressions under <code>consistency</code> are where they'd stop. Next: ready-made fact types (an Indian-rupee amount, a claim id) so nobody writes a regular expression."),
    ("Is anything missing that an FNOL ops lead would want checked?",
     "Nothing added until a real FNOL ops lead asks; rules come from the spec."),
    ("The comments explain each rule. Would you rather have a separate plain-English description field on each rule, which reports would show?",
     "Yes. Every rule takes an optional <code>description</code>, and the FNOL example now has one per rule. Built."),
])}
"""


@page("presets", "Presets: start from a ready-made set", "yaml",
      "Name a preset, then change, remove or add checks.", short="Presets")
def presets():
    src = (live.ROOT / "src/evalharness/presets/customer-support.yaml").read_text()
    return f"""
<div class="text">
<p>A preset is a ready-made set of checks for one kind of agent. Your file
names it, then changes it in three ways:</p>
<ul>
<li><b>Change a field:</b> write just that field; the rest of the check stays as the preset has it.</li>
<li><b>Remove a check:</b> write the check's name with <code>null</code> (the clothing agent removes groundedness, because its replies cite tool results, not documents).</li>
<li><b>Add a check:</b> write a new name, such as your domain patterns.</li>
</ul>
<p>A preset never ships a judge model: each team must add its own, so client data
never goes to a model the client didn't choose.</p>
</div>
{yaml_block(src, "src/evalharness/presets/customer-support.yaml")}
"""
