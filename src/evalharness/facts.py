"""Fact types: how a rules file names a kind of fact without writing a regular
expression (decision T26).

    facts:
      amount: inr_amount                 # a built-in type
      claim_id: {shape: "CLM-######"}    # a shape: # a digit, A a letter, the rest as written
      code: {pattern: "[A-Z]{3}\\\\d+"}     # a regular expression, for experts

Each type knows how to find its facts in text and how to compare them: an
amount is compared as a number, so "Rs. 12,400", "₹12,400" and "INR 12400" in
a reply all match 12400 in a tool result; an id is compared ignoring case and
spacing. A plain string that is not a built-in type's name is read as a
regular expression, as files written before fact types did.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FactType:
    name: str
    pattern: re.Pattern[str]
    normalise: Callable[[str], str | None]
    """A value as compared, or `None` when the text isn't this kind of fact."""
    words: str = ""
    """What it matches, in plain words, for error messages and the tutorial."""

    def find(self, text: str) -> list[str]:
        return [m.group(0) for m in self.pattern.finditer(text)]


def _amount(value: str) -> str | None:
    digits = re.sub(r"(?i)(rs\.?|inr|usd|us\$|\$|₹|,|\s)", "", value)
    try:
        number = float(digits)
    except ValueError:
        return None
    return str(int(number)) if number == int(number) else f"{number:.2f}"


def _id(value: str) -> str | None:
    cleaned = re.sub(r"[^0-9A-Za-z\-]", "", value).upper()
    return cleaned or None


def _plain(value: str) -> str | None:
    return value.strip().lower() or None


def _digits(value: str) -> str | None:
    d = re.sub(r"\D", "", value)
    return d[-10:] if len(d) >= 10 else None


AMOUNT = r"\d[\d,]*(?:\.\d+)?"
BUILT_IN: dict[str, FactType] = {
    t.name: t
    for t in (
        FactType(
            "inr_amount",
            re.compile(rf"(?:₹|\bRs\.?|\bINR)\s?{AMOUNT}", re.I),
            _amount,
            "an amount in rupees: ₹12,400, Rs. 12,400, INR 12400",
        ),
        FactType(
            "usd_amount",
            re.compile(rf"(?:\$|\bUSD\s?){AMOUNT}"),
            _amount,
            "an amount in dollars: $1,200, USD 1200",
        ),
        FactType(
            "percent",
            re.compile(r"\d+(?:\.\d+)?\s?%"),
            lambda v: _amount(v.replace("%", "")),
            "a percentage: 12%, 7.5 %",
        ),
        FactType("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), _plain, "an email address"),
        FactType(
            "phone_in",
            re.compile(r"(?:\+91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b"),
            _digits,
            "an Indian mobile number: 98765 43210, +91-9876543210",
        ),
        FactType("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), _id, "an Indian PAN: ABCDE1234F"),
    )
}


def shape(template: str) -> re.Pattern[str]:
    """A shape as a pattern: `#` a digit, `A` a letter, anything else as written."""
    parts = []
    for ch in template:
        parts.append(r"\d" if ch == "#" else "[A-Za-z]" if ch == "A" else re.escape(ch))
    return re.compile(r"\b" + "".join(parts) + r"\b")


def fact_type(name: str, spec: str | Mapping[str, Any]) -> FactType:
    """What a rules file wrote for one kind of fact, as a `FactType`."""
    if isinstance(spec, str):
        if spec in BUILT_IN:
            return BUILT_IN[spec]
        return FactType(name, re.compile(spec), _id, f"text matching {spec}")
    if "shape" in spec:
        return FactType(name, shape(str(spec["shape"])), _id, f"text shaped like {spec['shape']}")
    if "pattern" in spec:
        return FactType(
            name, re.compile(str(spec["pattern"])), _id, f"text matching {spec['pattern']}"
        )
    if "type" in spec and spec["type"] in BUILT_IN:
        return BUILT_IN[str(spec["type"])]
    known = ", ".join(sorted(BUILT_IN))
    raise TypeError(f"fact {name!r}: give a built-in type ({known}), a shape, or a pattern")
