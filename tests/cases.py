"""The requests every adapter is run on: one shape, four providers.

The core only describes tool calls and results (`ToolCallLike`, `ToolResultLike`);
a host brings its own. These two dataclasses are the tests' host.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from evalharness import EvalRequest, Expected, Meta, Passage, Response


@dataclass(frozen=True)
class Call:
    id: str
    name: str
    arguments: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Result:
    name: str
    structured: object = None
    text: str = ""
    is_error: bool = False


POLICY = (
    Passage("policy-7.2", "Windscreen damage is covered up to ₹15,000 with no excess."),
    Passage("claim-CLM-010003", "Claim CLM-010003 was approved on 12 Oct for ₹12,400."),
)
META = Meta(agent="claims-fnol", version="spike", position="online")

GET_CLAIM = Call("c1", "get_claim", {"id": "CLM-010003"})
PAYOUT = Call("c2", "issue_payout", {"id": "CLM-010003"})
CLAIM = Result("get_claim", {"id": "CLM-010003", "status": "approved"})

CASES: dict[str, EvalRequest] = {
    "grounded": EvalRequest(
        query="Is my windscreen claim approved?",
        response=Response("Yes, CLM-010003 was approved on 12 Oct for ₹12,400."),
        context=POLICY,
        meta=META,
    ),
    "ungrounded": EvalRequest(
        query="Is my windscreen claim approved?",
        response=Response("Yes, approved for ₹40,000, and your premium will not rise."),
        context=POLICY,
        meta=META,
    ),
    "payout_owed_not_called": EvalRequest(
        query="Please pay out my approved claim CLM-010003.",
        response=Response(
            "Your payout is on its way.", tool_calls=(GET_CLAIM,), tool_results=(CLAIM,)
        ),
        tool_definitions=({"type": "function", "function": {"name": "issue_payout"}},),
        expected=Expected(must_call=("get_claim", "issue_payout")),
        meta=META,
    ),
    "payout_called": EvalRequest(
        query="Please pay out my approved claim CLM-010003.",
        response=Response(
            "Done, ₹12,400 is on its way.", tool_calls=(GET_CLAIM, PAYOUT), tool_results=(CLAIM,)
        ),
        expected=Expected(must_call=("get_claim", "issue_payout")),
        meta=META,
    ),
    "pii_echo": EvalRequest(
        query="Update my phone number.",
        response=Response(
            "Thanks Priya Sharma, I've set your number to +91 98765 43210 "
            "and emailed priya.sharma@example.com."
        ),
        meta=META,
    ),
}
