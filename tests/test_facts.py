"""Fact types: naming a kind of fact without a regular expression."""

from __future__ import annotations

from typing import Any

import pytest

from evalharness import EvalRequest, Session, Step
from evalharness.facts import BUILT_IN, fact_type
from evalharness.patterns import Consistency


@pytest.mark.parametrize(
    ("spec", "text", "found", "normalised"),
    [
        ("inr_amount", "You get ₹12,400 today", ["₹12,400"], ["12400"]),
        ("inr_amount", "Rs. 12,400.00 is approved", ["Rs. 12,400.00"], ["12400"]),
        ("inr_amount", "INR 12400 and ₹ 500.50", ["INR 12400", "₹ 500.50"], ["12400", "500.50"]),
        ("usd_amount", "That's $1,200 or USD 99", ["$1,200", "USD 99"], ["1200", "99"]),
        ("percent", "a 7.5 % discount", ["7.5 %"], ["7.50"]),
        ("email", "write to ops@example.com.", ["ops@example.com."], ["ops@example.com."]),
        (
            "phone_in",
            "call +91-9876543210 or 98765 43210",
            ["+91-9876543210", "98765 43210"],
            ["9876543210", "9876543210"],
        ),
        ("pan", "PAN ABCDE1234F on file", ["ABCDE1234F"], ["ABCDE1234F"]),
        ({"shape": "CLM-######"}, "claim CLM-104233, not CLM-1042", ["CLM-104233"], ["CLM-104233"]),
        ({"shape": "AA-#####"}, "order ab-12345", ["ab-12345"], ["AB-12345"]),
        ({"pattern": "T\\d+"}, "ticket T42", ["T42"], ["T42"]),
        ("CLM-\\d{6}", "CLM-104233", ["CLM-104233"], ["CLM-104233"]),  # an older file's regex
    ],
)
def test_a_fact_type_finds_and_normalises(
    spec: Any, text: str, found: list[str], normalised: list[str]
) -> None:
    kind = fact_type("f", spec)
    assert kind.find(text) == found
    assert [kind.normalise(v) for v in found] == normalised


def test_a_wrong_fact_is_refused() -> None:
    with pytest.raises(TypeError, match="built-in type"):
        fact_type("f", {"colour": "blue"})


def test_every_built_in_type_says_what_it_matches() -> None:
    assert all(t.words for t in BUILT_IN.values())


FACTS = Consistency(facts={"amount": "inr_amount", "claim_id": {"shape": "CLM-######"}})


@pytest.mark.parametrize(
    ("reply", "result", "verdict"),
    [
        (
            "Approved: Rs. 12,400 for CLM-104233.",
            {"id": "CLM-104233", "approved_amount": 12400},
            "pass",
        ),
        ("Approved: ₹12,400.00.", {"approved_amount": "12400"}, "pass"),
        ("Approved: ₹15,000.", {"approved_amount": 12400}, "fail"),
        ("Your claim CLM-999999 is approved.", {"id": "CLM-104233"}, "fail"),
    ],
)
def test_consistency_compares_each_fact_its_own_way(
    reply: str, result: dict[str, Any], verdict: str
) -> None:
    steps = (
        Step("user", text="What will I get?"),
        Step("tool_call", name="get_claim"),
        Step("tool_result", name="get_claim", result=result),
        Step("assistant", text=reply),
    )
    assert FACTS.evaluate(EvalRequest(session=Session("s", steps))).verdict == verdict
