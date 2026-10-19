"""Saved questions: the questions ops teams ask every week, answered the same
way every time.

"Show me the under-escalations from last week" should not depend on how an AI
model phrases a query. A saved question is a name plus a filter over results
(which pattern, which kind of finding); `answer` lists the matching findings
from results already computed, by plain filtering. The same definition is
what each tool's version is generated from: a saved filter in LangSmith or
Langfuse, a KQL query for App Insights, a panel in Grafana, and a tool the
conversation layer calls by name before it ever composes a query of its own.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from evalharness.core import EvalResult


@dataclass(frozen=True)
class Question:
    name: str
    title: str
    """What an ops person would ask, in their words."""
    pattern: str
    """The pattern whose results it reads (`decision_vs_should`)."""
    finding: str
    """The kind of finding it lists (`under`, `over`, `claim_not_backed`)."""


@dataclass(frozen=True)
class Row:
    """One answer: which conversation, which rule, what it said."""

    session: str
    rule: str
    finding: str
    label: str


QUESTIONS = (
    Question(
        "under_escalations",
        "Where should the agent have handed over or asked for approval, and didn't?",
        "decision_vs_should",
        "under",
    ),
    Question(
        "over_escalations",
        "Where did the agent hand over or ask for approval with no rule calling for it?",
        "decision_vs_should",
        "over",
    ),
    Question(
        "promises_not_kept",
        "Where did the agent say something was done when it wasn't?",
        "claim_needs_action",
        "claim_not_backed",
    ),
    Question(
        "actions_without_prerequisite",
        "Where did the agent act without doing the required step first?",
        "requires_before",
        "missing_before",
    ),
    Question(
        "limits_exceeded",
        "Where did a tool argument go past its limit?",
        "argument_limit",
        "argument_limit",
    ),
    Question(
        "unsupported_facts",
        "Where did the agent state a fact no system gave it?",
        "consistency",
        "unsupported_fact",
    ),
)
"""The built-in saved questions, one or two per pattern."""

BY_NAME = {q.name: q for q in QUESTIONS}


def answer(question: Question, results: Iterable[tuple[str, EvalResult]]) -> list[Row]:
    """The findings that answer `question`, from `(pattern kind, result)` pairs,
    in the order given. Same results in, same rows out."""
    rows = []
    for kind, result in results:
        if kind != question.pattern:
            continue
        session = str(result.raw.get("session", ""))
        for found in result.raw.get("findings", ()):
            if found.get("kind") == question.finding:
                rows.append(
                    Row(session, result.evaluator, question.finding, str(found.get("label", "")))
                )
    return rows


def to_kql(question: Question, *, days: int = 7, synthetic: bool = False) -> str:
    """The question as an App Insights (KQL) query over the verdicts our sink
    writes (`evalharness.sinks.otel_events`): one row per conversation that
    answers it, newest first. Generated from the same definition `answer` uses,
    so the dashboard, the alert and the chat ask the same question."""
    keep = "" if synthetic else "\n| where tostring(p['evalharness.synthetic']) != 'True'"
    return (
        "AppTraces\n"
        f"| where TimeGenerated > ago({days}d)\n"
        "| extend p = parse_json(Properties)\n"
        f"| where tostring(p['evalharness.check']) == '{question.pattern}'\n"
        f"| where split(tostring(p['evalharness.finding_kinds']), ',') has '{question.finding}'"
        f"{keep}\n"
        "| project TimeGenerated, OperationId,\n"
        "    rule = tostring(p['gen_ai.evaluation.name']),\n"
        "    session = tostring(p['evalharness.session.id']),\n"
        "    requirements = tostring(p['evalharness.requirements'])\n"
        "| order by TimeGenerated desc"
    )
