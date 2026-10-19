"""Real data for the pages, made by running evalharness at build time.

Every example result on a page comes from here: the framework's own code run
on the repo's own fixtures and examples. If the code changes, the pages change
on the next build; nothing on a page is typed in by hand.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalharness import EvalRequest, Session, Step  # noqa: E402
from evalharness.patterns import (  # noqa: E402
    ArgumentLimit,
    ClaimNeedsAction,
    Consistency,
    DecisionVsShould,
    RequiresBefore,
)
from evalharness.traces import OtlpFile, sessions  # noqa: E402

RECORDED = ROOT / "tests" / "fixtures" / "otlp" / "pydantic_ai_refunds.jsonl"
FNOL_YAML = ROOT / "examples" / "claims-fnol.yaml"


def run(pattern, session):
    """One pattern on one session: the EvalResult, exactly as the framework returns it."""
    return pattern.evaluate(EvalRequest(session=session))


# --------------------------------------------------------------- recorded traces

def recorded_spans():
    return list(OtlpFile(RECORDED).spans())


def recorded_sessions():
    return {s.id: s for s in sessions(recorded_spans())}


REFUND_RULE = RequiresBefore(name="refund_needs_lookup", action="issue_refund",
                             before="get_order", same=["order_id"])


# --------------------------------------------------------- tiny example sessions
# One passing and one failing session per pattern, in FNOL's vocabulary.

def u(t):
    return Step("user", text=t)


def say(t):
    return Step("assistant", text=t)


def call(name, cid="", **args):
    return Step("tool_call", name=name, arguments=args, call_id=cid)


def ok(name, result=None, cid=""):
    return Step("tool_result", name=name, result=result, call_id=cid)


def bad(name, cid=""):
    return Step("tool_result", name=name, is_error=True, call_id=cid)


def decide(name):
    return Step("decision", name=name)


CLAIM = {"id": "CLM-104233", "status": "approved", "approved_amount": 12400}
BIG = {"id": "CLM-104990", "status": "approved", "approved_amount": 61000}

EXAMPLES = {
    "requires_before": dict(
        pattern=RequiresBefore(name="payout_needs_claim_lookup", action="issue_payout",
                               before="get_claim", same=["id"]),
        yaml="""payout_needs_claim_lookup:
  adapter: requires_before
  action: issue_payout
  before: get_claim
  same: [id]""",
        good=[u("Please pay claim CLM-104233."), call("get_claim", id="CLM-104233"), ok("get_claim", CLAIM),
              call("issue_payout", id="CLM-104233"), ok("issue_payout", {"paid": True}),
              say("The payout for CLM-104233 has been issued.")],
        bad=[u("Please pay claim CLM-104233."), call("issue_payout", id="CLM-104233"),
             ok("issue_payout", {"paid": True}), say("The payout for CLM-104233 has been issued.")],
    ),
    "argument_limit": dict(
        pattern=ArgumentLimit(name="refund_cap", tool="issue_refund", field="amount", max=10000),
        yaml="""refund_cap:
  adapter: argument_limit
  tool: issue_refund
  field: amount
  max: 10000""",
        good=[u("Refund my jacket, order 881."), call("issue_refund", order_id="881", amount=4999),
              ok("issue_refund", {"refunded": 4999}), say("Your refund of ₹4,999 is on its way.")],
        bad=[u("Refund my sofa, order 902."), call("issue_refund", order_id="902", amount=48000),
             ok("issue_refund", {"refunded": 48000}), say("Your refund of ₹48,000 is on its way.")],
    ),
    "claim_needs_action": dict(
        pattern=ClaimNeedsAction(name="payout_promise_kept", claims={
            "payout_sent": {"phrases": ["has been paid", "has been issued"], "tool": "issue_payout"}}),
        yaml="""payout_promise_kept:
  adapter: claim_needs_action
  claims:
    payout_sent:
      phrases: ["has been paid", "has been issued"]
      tool: issue_payout""",
        good=[u("Is my claim paid?"), call("get_claim", id="CLM-104233"), ok("get_claim", CLAIM),
              say("Nothing has been paid yet; it is approved and will be issued today.")],
        bad=[u("Is my claim paid?"), call("get_claim", id="CLM-104233"), ok("get_claim", CLAIM),
             say("Good news: your claim has been paid.")],
    ),
    "decision_vs_should": dict(
        pattern=DecisionVsShould(name="payout_approval", decision="awaiting_approval", when=[
            {"all": [{"tool_called": "request_payout"},
                     {"result_of": "get_claim", "field": "approved_amount", "above": 25000}]}]),
        yaml="""payout_approval:
  adapter: decision_vs_should
  decision: awaiting_approval
  when:
    - all:
        - {tool_called: request_payout}
        - {result_of: get_claim, field: approved_amount, above: 25000}""",
        good=[u("Pay claim CLM-104990 please."), call("get_claim", id="CLM-104990"), ok("get_claim", BIG),
              call("request_payout", id="CLM-104990"), ok("request_payout", {"queued": True}),
              decide("awaiting_approval"), say("A colleague will approve this payout shortly.")],
        bad=[u("Pay claim CLM-104990 please."), call("get_claim", id="CLM-104990"), ok("get_claim", BIG),
             call("request_payout", id="CLM-104990"), ok("request_payout", {"queued": True}),
             say("Your payout is being processed.")],
    ),
    "consistency": dict(
        pattern=Consistency(name="facts_from_systems", facts={"claim_id": {"shape": "CLM-######"},
                                                              "amount": "inr_amount"}),
        yaml="""facts_from_systems:
  adapter: consistency
  facts:
    claim_id: {shape: "CLM-######"}   # # a digit, A a letter
    amount: inr_amount              # ₹12,400 · Rs. 12,400 · INR 12400""",
        good=[u("How much will I get for CLM-104233?"), call("get_claim", id="CLM-104233"),
              ok("get_claim", CLAIM), say("Claim CLM-104233 is approved for ₹12,400.")],
        bad=[u("How much will I get for CLM-104233?"), call("get_claim", id="CLM-104233"),
             ok("get_claim", CLAIM), say("Claim CLM-104233 is approved for ₹15,000.")],
    ),
}


def example(kind, which):
    ex = EXAMPLES[kind]
    session = Session(f"{kind}-{which}", tuple(ex[which]))
    return session, run(ex["pattern"], session)


def fnol_yaml():
    return FNOL_YAML.read_text()


def cut(path, start, end=None):
    """Lines of a repo file from the first line matching `start` up to (not
    including) the next line matching `end`. Returns (text, first line number)."""
    lines = (ROOT / path).read_text().splitlines()
    i = next((n for n, line in enumerate(lines) if re.search(start, line)), None)
    if i is None:
        MISSING.append(f"{path}: {start}")
        return "code not found", 0
    j = len(lines)
    if end:
        j = next((n for n in range(i + 1, len(lines)) if re.search(end, lines[n])), len(lines))
    return "\n".join(lines[i:j]).rstrip(), i + 1


MISSING = []


def pretty(value):
    return json.dumps(value, ensure_ascii=False)
