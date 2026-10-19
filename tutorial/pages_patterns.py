"""The five domain patterns: one page each, with a passing and a failing session
run through the real code at build time."""

import live
from draw import flags_of, result_card, session_figure
from kit import note, table
from pages_session import yaml_block
from reg import link, page, review

INFO = {
    "requires_before": dict(
        title="requires_before: do A before B", q="Was the claim read before it was paid?",
        lesson="""<p>Some actions are only safe after another one. Never pay a claim nobody
has read; never cancel an order you haven't looked up. You name the action
(<code>issue_payout</code>), the one that must come first (<code>get_claim</code>),
and, optionally, which arguments must match (<code>same: [id]</code>), so reading
claim A doesn't count as reading claim B.</p>
<p>The earlier call must also have <b>succeeded</b>: a lookup that failed doesn't count.</p>""",
        limits=["It checks order, not content: it doesn't check that the claim said “approved”. "
                "For that, use <code>decision_vs_should</code> with <code>result_of</code>.",
                "The score is the share of <code>issue_payout</code> calls that had a lookup first."],
        questions=[("In your ops world, what are the top three “A before B” rules? Do they all fit this shape?",
                    "Starting set: pay only after reading the claim; cancel or refund only after reading the order; change account details only after verifying the customer. All three fit this shape.")],
    ),
    "argument_limit": dict(
        title="argument_limit: a number must stay within a limit", q="Was a refund above ₹10,000 sent?",
        lesson="""<p>A tool argument must stay below (or above) a value: a refund cap, a
discount cap, a maximum quantity. You name the tool, the argument, and
<code>max</code> or <code>min</code>.</p>""",
        limits=["It reads only what's <i>in the call</i>. FNOL's <code>issue_payout(id)</code> has no amount: "
                "the amount lives on the claim. So FNOL's limit is written with "
                "<code>decision_vs_should</code> and <code>result_of: get_claim</code> instead. We only "
                "learned that by running on FNOL's real conversations.",
                "An argument that isn't a number is skipped, not failed."],
        questions=[("Are limits in your world usually on the call itself, or on a record the agent read first (like FNOL)?",
                    "Both happen. A limit on the call uses <code>argument_limit</code>; a limit on a record the agent read uses <code>decision_vs_should</code> with <code>result_of</code>, as FNOL does. No change needed.")],
    ),
    "claim_needs_action": dict(
        title="claim_needs_action: don't say it unless it happened", q="Did it say “paid” when nothing was paid?",
        lesson="""<p>The most damaging mistake an agent makes is saying something was done
when it wasn't. You list the phrases that mean “done” in the agent's own
wording, and the tool that actually does it. If a reply contains the phrase,
that tool must have succeeded earlier.</p>
<p>Two guards stop false alarms: a <b>question</b> is not a claim, and a sentence
with a <b>negation</b> (“Nothing has been paid yet”) is not a claim. The pass
example below is exactly that case.</p>""",
        limits=["Phrases come from the agent's real replies; guessed phrases miss.",
                "A mixed sentence (“Your refund has been issued, not the replacement”) is skipped because of "
                "the “not”. That's a known miss, traded for no false alarms.",
                "A later version asks an AI judge what the reply claims, for wording the phrases don't cover."],
        questions=[("Is phrase matching good enough to start with, or would you rather pay for an AI judge from day one?",
                    "Phrases first. The AI-judge version comes later as an opt-in per rule, for teams that will pay for it."),
                   ("Which “done” claims matter most in your world (paid, refunded, cancelled, booked, escalated)?",
                    "Paid, refunded, cancelled and handed over first; booked when a booking agent comes along.")],
    ),
    "decision_vs_should": dict(
        title="decision_vs_should: decide when the rules say", q="Was a person asked to approve a large payout?",
        lesson="""<p>Some moments need a decision: ask a person to approve, hand over to a
human. You name the decision and list <b>when</b> it should happen. The check
finds two mistakes:</p>
<ul><li><b>Under:</b> it should have been made and wasn't (a ₹61,000 payout with no approval).</li>
<li><b>Over:</b> it was made with no rule calling for it (a needless hand-over).</li></ul>
<p>Conditions you can use: <code>user_says</code>, <code>tool_called</code>,
<code>result_of</code> (what a tool returned), <code>tool</code> (an argument above a value),
<code>failed_calls_at_least</code>, <code>consecutive_failed_at_least</code>, and
<code>all:</code> to need several at once.</p>""",
        limits=["Judged per window: only the steps since the previous such decision count, so failures before "
                "a person handed back don't count toward the next hand-over.",
                "If you list only some of the spec's triggers, set <code>check: under</code>. Otherwise a hand-over "
                "for a reason you didn't list looks needless.",
                "The agent must record its decisions. Standard traces have no field for this yet "
                "(" + link("trace-gaps", "see gaps") + ")."],
        questions=[("Is “under” and “over” the right way to talk about this to ops people, or would they say it differently?",
                    "Keep <code>under</code> and <code>over</code> in the YAML; reports say “missed” and “needless”.")],
    ),
    "consistency": dict(
        title="consistency: facts must come from a system", q="Did it state an amount no system gave it?",
        lesson="""<p>Every fact of a named kind in a reply (a claim id, an amount) must
appear in an earlier tool result, or in what the customer said. You name each
kind of fact without writing a regular expression: a built-in type such as
<code>inr_amount</code>, or a shape such as <code>CLM-######</code> (<code>#</code> a digit, <code>A</code> a letter).
Each type compares values its own way, so “Rs. 12,400”, “₹12,400” and 12400 in a result all match.</p>""",
        limits=["It catches invented facts, not wrong arithmetic done on true ones.",
                "Repeating the customer's own claim id back is allowed; that's not inventing it."],
        questions=[("Which facts would an ops team most want guarded: amounts, ids, dates, policy terms?",
                    "Amounts and ids now. Dates next, because they need one format before they can be compared.")],
    ),
}


@page("patterns", "Five patterns for whole conversations", None,
      "Reusable rules: you fill in your tool names and limits with YAML.", short="Five patterns")
def patterns():
    rows = [[link(f"p-{k.replace('_', '-')}", f"<code>{k}</code>"), v["q"]] for k, v in INFO.items()]
    return f"""
<div class="text">
<p>Most of the questions ops teams ask about an agent fit five shapes. Each shape
is a <b>pattern</b>: plain code that reads a session, written once by us. A
domain team fills it in with their own tool names and limits in YAML; they don't
write code.</p>
</div>
{table(["Pattern", "The kind of question it answers"], rows)}
{note("How every pattern answers", "<p>Each pattern counts how many things it checked and which failed. The <b>score</b> is the share that held (1.0 when nothing applied). <b>Any failure fails the check</b>, and each failure says what and at which step. No AI model is involved: the same session always gets the same verdict.</p>")}
<div class="text"><p>Each page below shows one passing and one failing conversation. Both
were run through the real code when this page was built; the verdicts are its
actual output.</p></div>
"""


def _caption(session, result):
    if any(i < len(session.steps) for i in flags_of(result)):
        return "Fails: the hatched step is where the check found the problem."
    return "Fails: nothing is wrong with any one step; what's missing is a step that should be there."


def _pattern_page(kind):
    info = INFO[kind]
    ex = live.EXAMPLES[kind]

    def render():
        good, good_r = live.example(kind, "good")
        bad, bad_r = live.example(kind, "bad")
        limits = "".join(f"<li>{x}</li>" for x in info["limits"])
        return f"""
<div class="text"><p class="lede">The question: <b>{info['q']}</b></p>{info['lesson']}</div>
{yaml_block(ex['yaml'], "The rule, as you'd write it in YAML")}
<h2>A conversation that passes</h2>
{session_figure(good, "Passes.")}
{result_card(good_r)}
<h2>A conversation that fails</h2>
{session_figure(bad, _caption(bad, bad_r), flags_of(bad_r))}
{result_card(bad_r)}
<h2>What it can't see</h2>
<div class="text"><ul>{limits}</ul></div>
{review(f"p-{kind.replace('_', '-')}", kind, info['questions'])}
"""
    return render


for _kind, _info in INFO.items():
    page(f"p-{_kind.replace('_', '-')}", _info["title"], "patterns", _info["q"], short=_kind)(_pattern_page(_kind))
