"""Sessions: the lesson, the shape in code, and how one is built."""

from html import escape

import live
from draw import session_figure
from kit import box, fig, flow3, note, path, table, text
from reg import link, page, review

REPO = "https://github.com/dataagentsai/eval-harness-framework/blob/main/"


def code(rel, start, end=None, title=""):
    """A piece of the real source, cut at build time, with file:line."""
    src, line = live.cut(rel, start, end)
    return (f'<div class="snip"><div class="snip-h"><span>{title}</span>'
            f'<a href="{REPO}{rel}#L{line}"><code>{rel}:{line}</code></a></div>'
            f'<pre>{escape(src)}</pre></div>')


def yaml_block(src, title=""):
    return (f'<div class="snip"><div class="snip-h"><span>{title}</span></div>'
            f'<pre>{escape(src)}</pre></div>')


@page("session", "What a session is", None,
      "One whole conversation, as an ordered list of steps.", short="Sessions")
def session():
    good, _ = live.example("requires_before", "good")
    return f"""
<div class="text">
<p>A <b>session</b> is one whole conversation between a customer and the agent,
written down as a list of <b>steps</b> in the order they happened. It's the one
thing every conversation-level check reads.</p>
<p>Here is a real one, in FNOL's words. A customer asks for a payout; the agent
reads the claim, pays it, and says so:</p>
</div>
{session_figure(good, "Six steps, top to bottom. Each box is one Step; its lane says who did it.")}
<h2>The five kinds of step</h2>
{table(["Kind", "What it records", "Drawn as"], [
    ["<code>user</code>", "What the customer typed", "left lane"],
    ["<code>assistant</code>", "What the agent replied", "middle lane"],
    ["<code>tool_call</code>", "The agent asked a system to do something: its name and arguments", "right lane, dark"],
    ["<code>tool_result</code>", "What the system answered, or that it failed", "right lane, light"],
    ["<code>decision</code>", "Something decided outside a tool, such as handing over to a person", "middle lane, dashed"],
])}
<div class="text">
<p><b>Why order matters.</b> “Was the claim read <i>before</i> the payout?” only
makes sense when the steps are in order. That's why a session is a list, not
a bag of facts.</p>
<p><b>Why calls and results are separate steps.</b> Asking for a payout and the
payout succeeding are different things. A check like “don't say it's paid unless
it was” needs the result, not just the call. A result is matched to its call by
an id (<code>call_id</code>) when the agent records one, or else by tool name.</p>
<p><b>Turns.</b> Each step also carries a <code>turn</code> number: turn 1 starts
with the customer's first message, turn 2 with their second, and so on.</p>
</div>
{note("Where sessions come from", "<p>Two ways today: from chat messages in OpenAI's format (" + link("from-messages", "how") + "), or rebuilt from the agent's traces (" + link("traces", "how") + "). Either way, the checks see the same shape.</p>")}
"""


@page("session-shape", "The Session in code", "session",
      "Two small classes, the class diagram, and what isn't in them yet.", short="In code")
def session_shape():
    diagram = "".join([
        box(20, 20, 330, 220, "Session", ["id: str", "steps: tuple[Step, ...]", "outcome: str", "",
                                          "calls(name) → the tool calls", "succeeded(i) → did call i work?",
                                          "from_messages(id, messages)"], "solid"),
        path("M350 130 L470 130"),
        text(410, 118, "has many, in order", "sm", "middle"),
        box(470, 20, 330, 220, "Step", ["kind: user · assistant ·", "  tool_call · tool_result · decision",
                                        "name: str   (tool or decision)", "text: str", "arguments: dict",
                                        "result: object", "call_id: str", "is_error: bool · turn: int"], "bx"),
        box(830, 70, 190, 110, "EvalRequest", ["session: Session", "(what every check", "is handed)"], "bxm"),
        path("M830 125 L350 60", "lnd", end=False),
    ])
    return f"""
<div class="text"><p>The whole shape is two small classes. Both are frozen
(they can't be changed once built), so a check can never alter what another
check will read.</p></div>
{fig(1040, 260, diagram, "Class diagram", "Session holds Steps in order. A check is handed an EvalRequest, which carries the Session.")}
{code("src/evalharness/core.py", r"^StepKind = ", r"^    @classmethod", "Step and Session")}
<h2>What a session does not hold yet</h2>
{table(["Missing", "Why it might matter", "Today"], [
    ["Time of each step", "“Replied within 2 minutes”, “waited 10 minutes for a person”", "Order only, no times"],
    ["Cost of each step", "“This conversation cost ₹40 in model calls”", "Not on the session; the cost engine will read calls separately"],
    ["How it ended", "Resolved, abandoned, escalated", "The <code>outcome</code> field exists but traces rarely fill it"],
    ["Who the customer is", "Per-customer limits (“3 refunds a month”)", "Kept on the request's meta, never sent to a vendor"],
])}
{review("session-shape", "The Session shape", [
    "Are the five kinds of step enough? Is there anything an ops person asks about that isn't one of them (for example a guardrail blocking a reply, or a person replying after a hand-over)?",
    "Should each step carry its time? It costs little, and enables “how long did the customer wait” rules.",
    "For <code>outcome</code>: which words should a conversation end with in your world (resolved, abandoned, escalated, something else)?",
])}
"""


@page("from-messages", "Building a session from chat messages", "session",
      "The simplest way in: the message list most frameworks can export.", short="From chat messages")
def from_messages():
    msgs = '''[
  {"role": "user", "content": "Please pay claim CLM-104233."},
  {"role": "assistant", "tool_calls": [{"id": "c1", "function":
      {"name": "get_claim", "arguments": "{\\"id\\": \\"CLM-104233\\"}"}}]},
  {"role": "tool", "name": "get_claim", "tool_call_id": "c1",
   "content": "{\\"approved_amount\\": 12400}"},
  {"role": "assistant", "content": "Claim CLM-104233 is approved for ₹12,400."}
]'''
    return f"""
<div class="text"><p>Almost every agent framework can hand you the conversation as
a list of messages in OpenAI's format. <code>Session.from_messages</code> turns
that list into steps, one message at a time.</p></div>
{flow3("A list of chat messages (user, assistant, tool)",
       "Each user message starts a new turn. An assistant message becomes a reply step, plus one tool_call step per tool it asked for. A tool message becomes a tool_result.",
       "A Session with its steps in order")}
{yaml_block(msgs, "Goes in: four messages")}
<div class="text"><p>Comes out: <code>user</code>, <code>tool_call get_claim</code>,
<code>tool_result get_claim</code>, <code>assistant</code>, all in turn 1.</p></div>
{code("src/evalharness/core.py", r"    def from_messages", r"^@dataclass", "The code")}
<div class="text"><p><b>What chat messages can't tell us:</b> decisions (a hand-over
is usually not a message) and whether a tool failed (most formats have no error
flag). Traces carry more; see {link("traces", "From traces")}.</p></div>
"""
