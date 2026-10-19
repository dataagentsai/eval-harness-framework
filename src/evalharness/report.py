"""The weekly report: one agent's verdicts over a week, counted the same way
every time.

It reads only verdicts (what `evalharness.sinks.otel_events` wrote), never a
conversation, so it holds no customer content and runs wherever the verdicts
are. Nothing in it is written by a model: every number is a count, every list
is a filter, and the same week always gives the same report.

Sections: per rule, how many conversations passed, failed, had nothing to
check, or could not be judged, and the failure rate among those judged, beside
the week before; the saved questions' answers; which requirements were
broken and how often; and how much could not be judged, so a quiet week is
never mistaken for a good one.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from typing import Any

from evalharness.questions import QUESTIONS, Question


@dataclass(frozen=True)
class Verdict:
    """One verdict event, read back."""

    at: float
    rule: str
    check: str
    label: str
    """`pass`, `fail`, `not_applicable`, `skip` or `error`."""
    session: str = ""
    trace: str = ""
    requirements: tuple[str, ...] = ()
    finding_kinds: tuple[str, ...] = ()
    agent: str = ""
    synthetic: bool = False

    @classmethod
    def of(cls, at: float, attributes: Mapping[str, Any], trace: str = "") -> Verdict:
        a = attributes

        def listed(key: str) -> tuple[str, ...]:
            return tuple(x for x in str(a.get(key) or "").split(",") if x)

        return cls(
            at=at,
            rule=str(a.get("gen_ai.evaluation.name", "")),
            check=str(a.get("evalharness.check", "")),
            label=str(a.get("gen_ai.evaluation.score.label", "")),
            session=str(a.get("evalharness.session.id", "")),
            trace=trace,
            requirements=listed("evalharness.requirements"),
            finding_kinds=listed("evalharness.finding_kinds"),
            agent=str(a.get("evalharness.agent", "")),
            synthetic=str(a.get("evalharness.synthetic", "")).lower() == "true",
        )


def matches(question: Question, verdict: Verdict) -> bool:
    """The same test `questions.to_kql` writes in KQL."""
    return verdict.check == question.pattern and question.finding in verdict.finding_kinds


@dataclass(frozen=True)
class RuleLine:
    rule: str
    counts: Mapping[str, int]
    before: Mapping[str, int] = field(default_factory=dict)

    @staticmethod
    def rate(counts: Mapping[str, int]) -> float | None:
        """Failures among the conversations actually judged (pass or fail)."""
        judged = counts.get("pass", 0) + counts.get("fail", 0)
        return None if judged == 0 else counts.get("fail", 0) / judged

    @property
    def fail_rate(self) -> float | None:
        return self.rate(self.counts)

    @property
    def change(self) -> str:
        now, then = self.rate(self.counts), self.rate(self.before)
        if now is None or then is None:
            return "no earlier week" if now is not None else "nothing judged"
        if abs(now - then) < 1e-9:
            return "same"
        return f"{'up' if now > then else 'down'} {abs(now - then) * 100:.0f} points"


@dataclass(frozen=True)
class Report:
    agent: str
    start: float
    end: float
    rules: tuple[RuleLine, ...]
    questions: Mapping[str, tuple[Verdict, ...]]
    requirements: Mapping[str, int]
    """How many failing verdicts named each requirement."""
    unnamed: int
    """Failing verdicts whose rule named no requirement: a gap in the rules file."""
    verdicts: int
    unjudged: int
    synthetic: bool
    """Whether test conversations were counted."""


def weekly(
    verdicts: Iterable[Verdict],
    *,
    start: float,
    end: float,
    previous: Iterable[Verdict] = (),
    agent: str = "",
    include_synthetic: bool = False,
) -> Report:
    def keep(v: Verdict) -> bool:
        return (include_synthetic or not v.synthetic) and (not agent or v.agent == agent)

    week = [v for v in verdicts if start <= v.at < end and keep(v)]
    before = [v for v in previous if keep(v)]
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for v in week:
        counts[v.rule][v.label] += 1
    earlier: dict[str, Counter[str]] = defaultdict(Counter)
    for v in before:
        earlier[v.rule][v.label] += 1
    broken: Counter[str] = Counter()
    for v in week:
        if v.label == "fail":
            broken.update(v.requirements)
    return Report(
        agent=agent,
        start=start,
        end=end,
        rules=tuple(RuleLine(r, dict(counts[r]), dict(earlier.get(r, {}))) for r in sorted(counts)),
        questions={q.name: tuple(v for v in week if matches(q, v)) for q in QUESTIONS},
        requirements=dict(broken.most_common()),
        unnamed=sum(1 for v in week if v.label == "fail" and not v.requirements),
        verdicts=len(week),
        unjudged=sum(1 for v in week if v.label == "skip"),
        synthetic=include_synthetic,
    )


def to_html(report: Report, *, title: str = "Weekly agent report") -> str:
    """A self-contained page: no scripts, no outside files, prints cleanly."""

    def day(ts: float) -> str:
        return datetime.fromtimestamp(ts, UTC).strftime("%d %b %Y")

    def pct(x: float | None) -> str:
        return "—" if x is None else f"{x * 100:.0f}%"

    rules = "".join(
        f"<tr><td><code>{escape(r.rule)}</code></td>"
        + "".join(
            f"<td>{r.counts.get(k, 0)}</td>" for k in ("pass", "fail", "not_applicable", "skip")
        )
        + f"<td><b>{pct(r.fail_rate)}</b></td><td>{escape(r.change)}</td></tr>"
        for r in report.rules
    )
    qs = []
    for q in QUESTIONS:
        found = report.questions.get(q.name, ())
        items = "".join(
            f"<li><code>{escape(v.session or v.trace)}</code>, {day(v.at)}, rule <code>{escape(v.rule)}</code>"
            + (f", requirements {escape(', '.join(v.requirements))}" if v.requirements else "")
            + "</li>"
            for v in found[:20]
        )
        more = f"<li>… and {len(found) - 20} more</li>" if len(found) > 20 else ""
        qs.append(
            f"<h3>{escape(q.title)} <span class=n>{len(found)}</span></h3>"
            + (f"<ul>{items}{more}</ul>" if found else "<p class=m>None this week.</p>")
        )
    reqs = (
        "".join(
            f"<tr><td><code>{escape(k)}</code></td><td>{n}</td></tr>"
            for k, n in report.requirements.items()
        )
        or "<tr><td colspan=2>No failing verdict named a requirement.</td></tr>"
    )
    unnamed = (
        f"<p class=m>{report.unnamed} failing verdict{'s' if report.unnamed != 1 else ''} came from rules that name no requirement: add <code>requirements:</code> to those rules.</p>"
        if report.unnamed
        else ""
    )
    test = (
        "<p class=warn>Includes test conversations (marked synthetic). Not a picture of real customers.</p>"
        if report.synthetic
        else ""
    )
    who = f" · {escape(report.agent)}" if report.agent else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
<style>
:root{{color-scheme:light}}body{{font:16px/1.5 system-ui,sans-serif;color:#222;background:#fff;max-width:900px;margin:0 auto;padding:24px 16px}}
h1{{margin:0 0 4px}}h2{{margin-top:32px;border-bottom:2px solid #222;padding-bottom:4px}}h3{{font-size:17px;margin:18px 0 4px}}
table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #ddd}}
th{{font-size:13px;text-transform:uppercase;color:#666}}code{{font-size:14px}}.m{{color:#666}}
.n{{display:inline-block;min-width:22px;text-align:center;border:1.5px solid #222;border-radius:10px;font-size:14px;margin-left:6px}}
.warn{{background:#FFF3C9;border:1.5px solid #222;padding:8px 12px;border-radius:8px}}.tw{{overflow-x:auto}}
</style></head><body>
<h1>{escape(title)}{who}</h1>
<p class=m>{day(report.start)} to {day(report.end)} · {report.verdicts} verdicts · counted from verdict events, no conversation content</p>
{test}
<h2>Rules</h2>
<p class=m>Fail rate counts only conversations a rule actually judged. “Nothing to check” and “could not judge” are shown apart, never as passes.</p>
<div class=tw><table><tr><th>Rule</th><th>Pass</th><th>Fail</th><th>Nothing to check</th><th>Could not judge</th><th>Fail rate</th><th>Vs. week before</th></tr>{rules}</table></div>
<p class=m>{report.unjudged} of {report.verdicts} verdicts could not be judged (what they needed was not recorded).</p>
<h2>Saved questions</h2>
{"".join(qs)}
<h2>Requirements broken</h2>
<div class=tw><table><tr><th>Requirement</th><th>Failing verdicts</th></tr>{reqs}</table></div>
{unnamed}
</body></html>
"""
