"""From traces: how a conversation is rebuilt from the agent's own traces,
followed step by step on a real recording."""

import live
from draw import flags_of, result_card, session_figure
from kit import box, fig, flow3, note, table, text
from reg import link, page, review, status


@page("traces", "From the agent's traces to a verdict", None,
      "One real conversation, followed from raw trace to failed check.", short="From traces")
def traces():
    spans = live.recorded_spans()
    sessions = live.recorded_sessions()
    convo = sessions["conv-no-lookup"]
    result = live.run(live.REFUND_RULE, convo)
    mine = [s for s in spans if s.attributes.get("gen_ai.conversation.id") == "conv-no-lookup"]
    span_rows = [[f"<code>{s.name}</code>", f"<code>{s.attributes.get('gen_ai.operation.name')}</code>",
                  "error" if s.error else "ok",
                  (f"<code>{s.attributes['gen_ai.tool.call.arguments']}</code>"
                   if "gen_ai.tool.call.arguments" in s.attributes else "—")] for s in mine]
    verdicts = [[f"<code>{sid}</code>", f"{len(s.steps)} steps",
                 f"<b>{live.run(live.REFUND_RULE, s).verdict}</b>"] for sid, s in sessions.items()]
    trace_pic = "".join([
        box(20, 20, 260, 70, "invoke_agent refund-agent", ["one agent run"], "bxm"),
        box(60, 110, 220, 54, "chat", ["model asks for issue_refund"], "bx"),
        box(60, 180, 220, 54, "execute_tool issue_refund", ["arguments + result"], "solid"),
        box(60, 250, 220, 54, "chat", ["model writes the reply"], "bx"),
        text(310, 50, "A trace is a tree of spans: one span per piece of work,", "tx"),
        text(310, 74, "each with a name, a start and end time, and attributes.", "tx"),
        text(310, 150, "gen_ai.input.messages / gen_ai.output.messages", "mn"),
        text(310, 214, "gen_ai.tool.name, gen_ai.tool.call.arguments, .result", "mn"),
        text(310, 280, "every span: gen_ai.conversation.id = conv-no-lookup", "mn"),
    ])
    return f"""
<div class="text">
<p>Most agents already write <b>traces</b>: a record of every piece of work, in
a standard format called OpenTelemetry. If we can rebuild conversations from
traces, a team adds <b>no code</b> to their agent to be checked. This page follows
one real recording through every step.</p>
</div>
{note("The recording", "<p>A small refund agent built with Pydantic AI, a framework we didn't write, with its own built-in tracing switched on. Its model is scripted, so no AI is called and the recording is identical every time (<code>scripts/record_genai_traces.py</code>). It has three conversations. We follow the one that refunds without looking the order up.</p>")}

<h2>1 · The agent runs, and writes spans</h2>
{fig(1000, 320, trace_pic, "One agent run as a span tree", "One agent run. The names in code font are the standard's attribute names: any framework that follows the standard writes the same ones.")}
<div class="text"><p>The whole recording is {len(spans)} spans. These are the ones for our conversation:</p></div>
{table(["Span", "Operation", "Status", "Tool arguments"], span_rows)}

<h2>2 · Group spans into conversations</h2>
{flow3("All spans, from every conversation", "Group by <code>gen_ai.conversation.id</code>; if missing, by <code>session.id</code>; if missing, each trace is its own conversation", f"{len(sessions)} groups, one per conversation")}

<h2>3 · Rebuild the steps</h2>
<div class="text"><p>Inside a group, spans are put in time order and turned into steps. The
customer's words come from the model's input messages; the replies from its
output messages; tool calls and results from the tool spans. Three traps, all
found on the real recording, are in {link("trace-rebuild", "how the rebuild works")}.</p></div>
{session_figure(convo, "The rebuilt session: the agent refunds with no lookup first.")}

<h2>4 · Run the rule</h2>
<div class="text"><p>The rule: <code>issue_refund</code> needs a successful <code>get_order</code> for the same <code>order_id</code> first.</p></div>
{session_figure(convo, "The check flags the refund.", flags_of(result))}
{result_card(result)}

<h2>5 · All three conversations</h2>
{table(["Conversation", "Size", "refund_needs_lookup"], verdicts)}
<div class="text"><p>The one that looked the order up first passes. The one where the lookup
failed passes too: it never refunded, so there was nothing to check.</p></div>
{review("traces", "From traces", [
    ("Is following one conversation from raw spans to verdict the right way to explain this, or too much detail?",
     "Yes, keep the one-conversation walk-through."),
    ("Phoenix is next (it's where many teams' traces already are). Is there a store your clients use more, such as App Insights or Langfuse?",
     "App Insights second (the Azure clients, and FNOL already writes there), then Langfuse."),
])}
"""


@page("trace-rebuild", "How the rebuild works: three traps", "traces",
      "What we found on a real framework's traces, and how the reader handles it.", short="Three traps")
def trace_rebuild():
    return f"""
<div class="text"><p>Rebuilding sounds simple. On a real framework's traces, three things
would have produced the wrong conversation:</p></div>
{table(["What we saw", "What would go wrong", "What the reader does"], [
    ["Every model call resends the whole conversation so far", "Each customer message would appear many times",
     "Takes only the customer's words after the model last spoke, once per trace"],
    ["Pydantic AI sends tool results back as customer messages with no text", "Extra empty “customer” turns",
     "A customer message with no text is not a turn"],
    ["Each tool call is recorded twice: in the model's output and as its own tool span",
     "Every call counted twice", "One step per call id; the result comes from the tool span when there is one"],
])}
<div class="text"><p>Each trap is a test in <code>tests/test_traces.py</code>, alongside cases
built by hand: no conversation id, an agent that doesn't resend history, calls
recorded only in messages, and a failed tool.</p></div>
"""


@page("trace-gaps", "What the standard can't say yet", "traces",
      "No field for a hand-over or for how a conversation ended.", short="Gaps in the standard")
def trace_gaps():
    return f"""
<div class="text">
<p>The OpenTelemetry standard for AI agents (the <i>GenAI conventions</i>) has
names for model calls, tool calls, messages, tokens and conversations. It has
<b>no name for a decision</b> such as handing over to a person, and <b>none for how
a conversation ended</b>.</p>
<p>So a session rebuilt from standard traces has no <code>decision</code> steps,
and {link("p-decision-vs-should", "decision_vs_should")} can't run on it until a team says
which of its own attributes means “handed over”. The reference agent records this as
<code>termination</code>; another team will use another name.</p>
</div>
{table(["What", "In the standard?", "In our reader"], [
    ["Conversation id", "Yes: <code>gen_ai.conversation.id</code>", status(True)],
    ["Messages in and out", "Yes", status(True)],
    ["Tool calls, arguments, results, errors", "Yes", status(True)],
    ["A hand-over or approval decision", "No", status(False, "map a team's own attribute in YAML")],
    ["How the conversation ended", "No", status(False)],
])}
{note("One standard already has it", "<p>OpenInference, the naming Phoenix's own instrumentors use, has span kinds <code>DECISION</code> and <code>GUARDRAIL</code>. Our Phoenix reader translates OpenInference model and tool spans today; reading its decision spans as hand-overs is the next step, and evidence for the OpenTelemetry proposal.</p>")}
{note("What we'll do about it", "<p>Two things: let a team map its own attribute to a decision in YAML, and add these gaps to our proposal to the OpenTelemetry group (Tier 11). The standard itself is still marked “in development”, so this is a good moment to propose it.</p>")}
{review("trace-gaps", "Gaps in the standard", [
    ("Should we propose a hand-over field to OpenTelemetry now, or wait until a second team needs it?",
     "Wait for a second team. Meanwhile a team maps its own attribute to a decision in YAML."),
])}
"""
