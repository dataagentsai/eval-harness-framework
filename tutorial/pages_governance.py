"""Governance and the decide step: who may change a rule, when a rule may
block, how a result becomes an action, and limits across conversations."""

from html import escape

from kit import arrow, box, fig, note, table
from pages_session import code, yaml_block
from reg import link, page, review

from evalharness.config import MIN_PRECISION, MIN_SAMPLE, ConfigRefused, build, layered
from evalharness.hooks import Event, Hooks, Redact, check
from evalharness.state import MemoryStore, limit_total

ORG = {"evaluators": {
    "pii": {"adapter": "presidio_pii", "locked": True, "owner": "risk-office",
            "at": "reply", "mode": "block"},
    "refund_cap": {"adapter": "argument_limit", "tool": "issue_refund", "field": "amount", "max": 10000},
}}


def _refused(evaluators):
    try:
        layered({"evaluators": evaluators}, ORG)
        return "accepted"
    except ConfigRefused as why:
        return f"refused: {escape(str(why))}"


def _gate(extra):
    rule = {"adapter": "argument_limit", "tool": "issue_refund", "field": "amount", "max": 10000,
            "at": "pre_tool", **extra}
    try:
        build({"evaluators": {"refund_cap": rule}})
        return "accepted"
    except ConfigRefused as why:
        return f"refused: {escape(str(why))}"


@page("arch-governance", "Who may change a rule, and when it may block", "arch",
      "Three layers of rules files, locked rules, an audit list, and the promotion gate.",
      short="Who may change a rule")
def governance():
    d = "".join([
        box(20, 40, 250, 100, "1 · Preset", ["ready-made checks", "for a kind of agent"], "bx"),
        arrow(270, 90, 330, 90),
        box(330, 40, 300, 100, "2 · The organisation's policy", ["risk office's file;", "can lock rules"], "solid"),
        arrow(630, 90, 690, 90),
        box(690, 40, 260, 100, "3 · The agent team's file", ["adds, changes, removes;", "can't touch locked rules"], "bxs"),
        arrow(950, 90, 990, 90),
        box(990, 50, 110, 80, "Rules", ["+ audit list"], "bx"),
    ])
    tries = [
        ("Remove the locked <code>pii</code> rule", _refused({"pii": None})),
        ("Switch the locked <code>pii</code> rule to shadow", _refused({"pii": {"mode": "shadow"}})),
        ("Raise the unlocked refund cap to ₹20,000", _refused({"refund_cap": {"max": 20000}})),
        ("Remove the unlocked refund cap", _refused({"refund_cap": None})),
    ]
    gates = [
        ("<code>mode: block</code>, nothing else", _gate({"mode": "block"})),
        ("…with an owner, no evidence", _gate({"mode": "block", "owner": "claims-ops"})),
        ("…with evidence: precision 0.80 on 200", _gate({"mode": "block", "owner": "claims-ops",
                                                       "evidence": {"precision": 0.8, "sample": 200, "measured": "2026-10-19"}})),
        ("…with evidence: precision 0.96 on 140", _gate({"mode": "block", "owner": "claims-ops",
                                                       "evidence": {"precision": 0.96, "sample": 140, "measured": "2026-10-19"}})),
    ]
    _, audit = layered({"evaluators": {"refund_cap": {"max": 20000},
                                       "lookup_first": {"adapter": "requires_before", "action": "issue_refund", "before": "get_order"}}}, ORG)
    return f"""
<div class="text">
<p>Your decision T22: an agent team may switch off its own rules, except rules the
risk owner locks. That needs three layers of rules files, read in order.</p>
</div>
{fig(1120, 170, d, "Three layers", "Each layer is laid over the one before, field by field. A locked rule from the organisation passes through untouched.")}
<h2>Tried when this page was built</h2>
{table(["The agent team's file tries to…", "Result"], [[a, b] for a, b in tries])}
<h3>The audit list</h3>
<div class="text"><p>Every change a team's file makes to a rule it inherited is listed, so a reviewer
reads one list instead of comparing files:</p></div>
{table(["Rule", "What changed", "Before", "After"], [[f"<code>{c.rule}</code>", c.field, escape(str(c.before)) if c.before is not None else "—", escape(str(c.after))] for c in audit])}
<h2>The promotion gate: when a rule may block</h2>
<div class="text"><p>A rule in shadow records what it would have done. It may move to <b>block</b> only
with a named <b>owner</b> and evidence from shadow: precision of at least {MIN_PRECISION} on at
least {MIN_SAMPLE} conversations, with the date it was measured. A rule the organisation locked
needs only its owner: that's the risk owner's call.</p></div>
{table(["The file says", "Result"], [[a, b] for a, b in gates])}
{yaml_block('''refund_cap:
  adapter: argument_limit
  tool: issue_refund
  field: amount
  max: 10000
  at: pre_tool
  mode: block
  owner: claims-ops                                # who answers for it
  evidence: {precision: 0.96, sample: 140, measured: 2026-10-19}''', "A rule that has earned the right to block")}
{note("Not built yet", "<p>The evidence is declared, and checked against the bar. Measuring it for you (a shadow rule's decisions against human labels) comes with the review queue in Tier 8.</p>")}
{review("arch-governance", "Who may change a rule", [
    f"Is {MIN_PRECISION} precision on {MIN_SAMPLE} conversations the right bar to block, or should it differ per kind of rule (a PII mask vs. stopping a refund)?",
])}
"""


@page("arch-decide", "Deciding, masking, and counting across conversations", "arch",
      "The decide step, masking PII instead of blocking, and per-customer limits.",
      short="Decide and count")
def decide():
    masked = _presidio_demo()
    store = MemoryStore(clock=lambda: 0.0)
    before, after = limit_total(store, tool="issue_refund", field="amount", max_total=20000,
                                window_s=30 * 86400, name="refund_total")
    hooks = Hooks()
    hooks.add("pre_tool", before, tools=["issue_refund"])
    hooks.add("post_tool", after, tools=["issue_refund"])
    rows = []
    for amount in (12000, 6000, 4000):
        d = hooks.run(Event("pre_tool", tool="issue_refund", arguments={"amount": amount}, user="C-17"))
        if d.action == "allow":
            hooks.run(Event("post_tool", tool="issue_refund", arguments={"amount": amount}, user="C-17",
                            result={"refunded": amount}))
        rows.append([f"₹{amount:,}", f"<b>{d.action}</b>", escape(d.reason) or "—"])
    return f"""
<div class="text">
<p>A check says what it found. The <b>decide step</b> (the <code>Policy</code> port) turns that
into one action, so the same check can block in one company and mask in another.</p>
</div>
{table(["Policy", "What a fail becomes"], [
    ["<code>OnFail</code> (the default)", "the rule's <code>on_fail</code>: block, escalate, or allow and record"],
    ["<code>Redact</code>", "for text the check located (Presidio gives each finding's position): the text goes through with those parts masked"],
])}
<h2>Masking a reply with Presidio</h2>
{masked}
{note("A bug the real run caught", "<p>Presidio reports overlapping hits: an email address, and “URLs” inside it. Masking the first hit only produced <code>[URL]arma@[URL]</code>, leaking part of the address. Overlapping hits are now merged into one region, named by the widest hit.</p>")}
<h2>A check that breaks never lets the action through</h2>
<div class="text"><p>Our adapters catch a vendor's exception and answer <code>error</code>. Read as “no
problem”, that let actions through when a check broke: the opposite of fail-closed. An
<code>error</code> now counts as a broken hook, so the moment's <code>on_error</code> decides
(closed by default, see {link("arch-hooks", "hooks")}).</p></div>
<h2>Limits across conversations</h2>
<div class="text"><p>“Refunds to one customer in 30 days must stay under ₹20,000” can't be judged in one
conversation. A running total per customer (the <code>StateStore</code> port) answers it: before
<code>issue_refund</code> runs, would this refund take customer C-17's 30-day total over the
limit? Three refunds, run when this page was built:</p></div>
{table(["Refund asked", "Decision", "Why"], rows)}
<div class="text"><p>Only refunds that succeeded are counted. The in-memory store suits tests and one
worker; several workers need a shared store (Redis), which is the same port.</p></div>
{code("src/evalharness/hooks.py", r"^class Redact", r"^def merged", "The masking policy, in real code")}
"""


def _presidio_demo():
    reply = "Your refund is on its way to priya.sharma@example.com; call 9876543210 if it isn't."
    try:
        pii = build({"evaluators": {"pii": {"adapter": "presidio_pii", "severity": {"DATE_TIME": 0.0}}}})["pii"]
        hooks = Hooks()
        hooks.add("reply", check(pii, policy=Redact()))
        d = hooks.run(Event("reply", text=reply))
        sent, how = d.text or reply, "run with Presidio when this page was built"
    except Exception:  # noqa: BLE001 (Presidio not installed where the page is built)
        sent = "Your refund is on its way to [EMAIL_ADDRESS]; call [PHONE_NUMBER] if it isn't."
        how = "recorded from a run on 20 Oct 2026 (Presidio isn't installed where this page was built)"
    return table(["", "Text"], [["The agent wrote", escape(reply)], ["The customer saw", f"<b>{escape(sent)}</b>"]]) + \
        f'<p class="deeper">{how}.</p>'
