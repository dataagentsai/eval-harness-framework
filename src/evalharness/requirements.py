"""Requirements: what a rule tests, looked up in the agent's spec.

A rule names the requirements it tests by their id in the team's spec
(`requirements: [P-PAYOUT]`). This module finds each id's wording in a spec
written in the AOAS shape, so a report can show the requirement beside the
verdict, and a misspelled id is caught before anything runs.

The id forms, as the specs write them:

- `P-PAYOUT`: a policy, under `policies`, or a statement under one of its
  groups (`policies.approval.statements`);
- `escalation.injury-reported`: a hand-over trigger under
  `policies.escalation` (`on_request`, `on_reply` or `on_condition`);
- `issue_payout.authority.agent_when`: a field of an operation;
- `personal_data_in_conversation`: any other key under `policies`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

TRIGGER_GROUPS = ("on_request", "on_reply", "on_condition")


def requirement(spec: Mapping[str, Any], rid: str) -> str | None:
    """The wording of requirement `rid` in `spec`, or `None` when it has none."""
    policies = spec.get("policies") or {}
    found = policies.get(rid)
    if isinstance(found, Mapping) and "rule" in found:
        return str(found["rule"])
    if found is not None:
        return _words(found)
    for group in policies.values():
        if isinstance(group, Mapping):
            for statement in group.get("statements") or ():
                if statement.get("id") == rid:
                    return str(statement["rule"])
    head, _, rest = rid.partition(".")
    if head == "escalation":
        escalation = policies.get("escalation") or {}
        for kind in TRIGGER_GROUPS:
            for trigger in escalation.get(kind) or ():
                if trigger.get("id") == rest:
                    return f"hand over to a person when {_words(trigger['when'])}"
    node: Any = (spec.get("operations") or {}).get(head)
    for key in rest.split(".") if rest else ():
        node = node.get(key) if isinstance(node, Mapping) else None
    return None if node is None or head not in (spec.get("operations") or {}) else _words(node)


def _words(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return "; ".join(value)
    return json.dumps(value, ensure_ascii=False)
