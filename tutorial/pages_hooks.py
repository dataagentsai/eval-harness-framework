"""Hooks in a loop of your own: how injection points stay simple and still
target one tool."""

from html import escape

import live
from kit import arrow, box, fig, note, table, text
from pages_session import code, yaml_block
from reg import link, page, review

from evalharness import Session, Step
from evalharness.hooks import Decision, Event, Hooks, check


def _demo():
    hooks, ran = Hooks(), []

    def spy(name, inner=None):
        def hook(event):
            ran.append(name)
            return inner(event) if inner else None
        hook.__name__ = name
        return hook

    hooks.add("pre_tool", spy("refund_needs_lookup", check(live.REFUND_RULE)), tools=["issue_refund"])
    hooks.add("pre_tool", spy("refund_cap", lambda e: Decision("escalate", "over ₹10,000")
                             if e.arguments.get("amount", 0) > 10000 else None), tools=["issue_refund"])
    hooks.add("pre_tool", spy("irreversible_needs_named_order", lambda e: None), side_effects=["irreversible"])
    hooks.add("post_tool", spy("pii_in_results", lambda e: None))
    looked_up = Session("s", (Step("user", text="refund 42"),
                              Step("tool_call", name="get_order", arguments={"order_id": "42"}),
                              Step("tool_result", name="get_order", result={"order_id": "42", "total": 500})))
    bare = Session("s", (Step("user", text="refund 42"),))
    events = [
        ("get_order, a read", Event("pre_tool", tool="get_order", arguments={"order_id": "42"},
                                    side_effect="read", session=bare)),
        ("issue_refund ₹500, order looked up", Event("pre_tool", tool="issue_refund", side_effect="irreversible",
                                                    arguments={"order_id": "42", "amount": 500}, session=looked_up)),
        ("issue_refund ₹500, no lookup", Event("pre_tool", tool="issue_refund", side_effect="irreversible",
                                              arguments={"order_id": "42", "amount": 500}, session=bare)),
        ("issue_refund ₹48,000, looked up", Event("pre_tool", tool="issue_refund", side_effect="irreversible",
                                                 arguments={"order_id": "42", "amount": 48000}, session=looked_up)),
        ("cancel_order, irreversible", Event("pre_tool", tool="cancel_order", side_effect="irreversible",
                                             arguments={"order_id": "42"}, session=bare)),
    ]
    rows = []
    for label, event in events:
        ran.clear()
        d = hooks.run(event)
        rows.append([escape(label), ", ".join(f"<code>{r}</code>" for r in ran) or "none",
                     f"<b>{d.action}</b>" + (f": {escape(d.reason)}" if d.reason else "")])
    return rows


@page("arch-hooks", "Hooks in a loop of your own", "arch",
      "Five lines in your loop, and a matcher on each hook to target one tool.", short="Hooks in your own loop")
def arch_hooks():
    d = "".join([
        box(20, 30, 300, 330, "Your loop (5 lines added)", ["", "hooks.run(pre_model)", "  model call",
                                                            "hooks.run(post_model)", "hooks.run(pre_tool)", "  tool runs",
                                                            "hooks.run(post_tool)", "hooks.run(reply)"], "bx"),
        arrow(320, 195, 400, 195, "event", ly=185),
        box(400, 120, 250, 150, "Hooks.run(event)", ["keep the hooks whose", "moment and matcher fit,",
                                                       "run them in order;", "first block wins"], "solid"),
        arrow(650, 195, 720, 195),
        text(720, 40, "HOOKS, each with a matcher", "lbl"),
        box(720, 55, 380, 56, "refund_needs_lookup", ["pre_tool · tools: issue_refund"], "bxs"),
        box(720, 122, 380, 56, "refund_cap", ["pre_tool · tools: issue_refund"], "bxs"),
        box(720, 189, 380, 56, "every irreversible tool", ["pre_tool · side_effect: irreversible"], "bxs"),
        box(720, 256, 380, 56, "pii_in_results", ["post_tool · every tool"], "bx"),
        box(720, 323, 380, 56, "redact the reply", ["reply"], "bx"),
    ])
    loop = '''for step in range(max_steps):
    hooks.run(Event("pre_model", text=prompt))              # 1
    reply = model(messages)
    hooks.run(Event("post_model", text=reply.text))         # 2
    for call in reply.tool_calls:
        d = hooks.run(Event("pre_tool", tool=call.name,     # 3
                            arguments=call.arguments,
                            side_effect=registry[call.name].side_effect,
                            session=session))
        if d.stops:                      # block or escalate: the tool never runs;
            result = refused(d)          # the model is told why
        else:
            result = tools[call.name](**(d.arguments or call.arguments))
            hooks.run(Event("post_tool", tool=call.name, result=result))   # 4
    ...
hooks.run(Event("reply", text=final_text))                  # 5'''
    deco = '''hooks = Hooks()

@hooks.before_tool("issue_refund")                 # one tool
def refund_cap(event):
    if event.arguments["amount"] > 10_000:
        return Decision("escalate", "refunds over ₹10,000 need a person")

@hooks.before_tool("issue_*")                      # a family of tools
def ...

@hooks.before_tool(side_effect="irreversible")     # every tool of a kind
def ...

hooks.add("pre_tool", check(refund_needs_lookup), tools=["issue_refund"])   # any of our checks'''
    yaml_src = '''evaluators:
  refund_needs_lookup:
    adapter: requires_before
    action: issue_refund
    before: get_order
    at: pre_tool               # the moment
    tools: [issue_refund]      # the matcher: which tools
    on_fail: block             # block · escalate · allow (just record)'''
    return f"""
<div class="text">
<p><b>Your question:</b> a framework gives us hooks before and after model and tool
calls. In our own loop, code added “before a tool call” runs for every tool. How
do we run something before <i>one</i> tool only, and keep injection points simple?</p>
<p><b>The answer is two separate jobs.</b></p>
<ol>
<li><b>The loop only reports the moment.</b> Five lines, one per moment, each saying
“here's what's happening”: which tool, its arguments, the conversation so far. These
lines never change, however many rules you add.</li>
<li><b>Each hook says what it's for.</b> Targeting lives on the hook, as a
<b>matcher</b>: one tool by name, a family by pattern (<code>issue_*</code>), or a whole
kind of tool (every <i>irreversible</i> one). The loop never has an <code>if tool == …</code>.</li>
</ol>
</div>
{fig(1120, 400, d, "Your loop, the hook runner, and hooks with matchers",
     "For an issue_refund call, the first three hooks fit and run; for get_order, none of them do. Adding a rule never touches the loop.")}
<h2>The five lines in your loop</h2>
{yaml_block(loop, "Your own loop, with the five moments marked")}
<h2>Targeting one tool, three ways</h2>
{yaml_block(deco, "In code: decorators, like a framework's hooks")}
{yaml_block(yaml_src, "In YAML: no code at all (what an ops person writes)")}
<h2>Try it: five tool calls, four hooks</h2>
<div class="text"><p>Run when this page was built: the hooks in the drawing, and five tool calls
the model asked for. Which hooks ran, and what was decided:</p></div>
{table(["Tool call", "Hooks that ran", "Decision"], _demo())}
<h2>What a decision does at each moment</h2>
{table(["Moment", "allow", "modify", "block", "escalate"], [
    ["before the model", "goes on", "changed prompt (redacted)", "turn ends with a safe reply", "hand to a person"],
    ["after the model", "goes on", "changed text", "the model's answer is not used", "hand to a person"],
    ["before a tool", "tool runs", "changed arguments", "tool doesn't run; the model is told why and may choose again", "a person approves first"],
    ["after a tool", "result goes into context", "redacted result", "result replaced by a notice (the action already happened)", "hand to a person"],
    ["the reply", "sent", "redacted reply", "safe reply instead", "hand to a person"],
])}
<h2>What we borrowed, and from where</h2>
{table(["Idea", "Borrowed from", "What it gives us"], [
    ["An event plus a matcher on the tool name", "Claude Code's PreToolUse and PostToolUse hooks", "One tool, a pattern, or all, without touching the loop"],
    ["A hook answers allow, deny or a changed input", "Same hooks", "Hooks can fix a call, not only stop it"],
    ["A check beside the call that can trip it", "Guardrails in the agent SDKs", "Our checks become hooks with one line: <code>check(...)</code>"],
    ["Before and after the model call, at the gateway", "LiteLLM's pre- and post-call guardrails", "The same hook can run at the gateway for model calls (Tier 7)"],
    ["Matching on the kind of tool, not its name", "Our specs: every operation declares its side effect", "New irreversible tools are covered without a new rule"],
])}
{note("Why this stays simple and effective", "<p><b>Simple:</b> one entry point, five calls, one decision type; rules are added in YAML or with a decorator, never in the loop. <b>Effective:</b> unmatched hooks cost nothing; the first block stops the rest; matching by kind of tool covers tools nobody listed; and the same hook runs in your loop, in a framework (an adapter turns its hook into an Event), or at the gateway. Still to come in Tier 3: a time budget per moment, fail-closed when a hook breaks, and every decision recorded on the trace.</p>")}
{code("src/evalharness/hooks.py", r"    def run\(self, event", r"^def check", "The hook runner, in real code")}
{review("arch-hooks", "Hooks in your own loop", [
    ("Is “the loop reports the moment, the hook says what it's for” simple enough to explain to an agent team?",
     "Recommended: yes, and lead with matching by kind of tool (irreversible, write), because it covers new tools without new rules."),
])}
<p class="deeper">Where each moment sits in a turn: {link("arch-modes", "offline, inline, online")}.</p>
"""
