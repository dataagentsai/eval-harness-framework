"""`evaluators.yaml`, read into built adapters, refusing to start when it is wrong.

    judge:                                   # one judge model for every judged check
      model: openai/gpt-oss-120b
      base_url: https://api.groq.com/openai/v1
      api_key_env: GROQ_API_KEY
      input_per_mtok: 0.15
      output_per_mtok: 0.75
    evaluators:                              # configured name -> adapter and its settings
      groundedness:
        adapter: azure_groundedness
        scale: {raw_min: 1, raw_max: 5, higher_is_better: true, threshold: 4}
      pii:
        adapter: presidio_pii
        severity: {URL: 0.0}

Choosing an adapter imports only its module (`evalharness.adapters.ADAPTERS`).
**Startup refuses** an unknown adapter, an unknown field, a judged adapter with
no judge, and a scale whose range is empty.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from evalharness.adapter import Adapter
from evalharness.adapters import ADAPTERS
from evalharness.core import Scale
from evalharness.hooks import MODES, POSITIONS, Hooks, Moment
from evalharness.hooks import check as as_hook
from evalharness.judge_model import JudgeModel
from evalharness.patterns import PATTERNS

KINDS = {**ADAPTERS, **PATTERNS}
"""Every buildable check: provider adapters and our domain patterns."""
PRESETS = Path(__file__).parent / "presets"

SCALE_FIELDS = frozenset({"raw_min", "raw_max", "higher_is_better", "threshold"})
PLACEMENT = ("at", "tools", "side_effects", "on_fail", "mode")
GOVERNANCE = ("locked", "owner", "evidence")
"""Who answers for a rule, and why it may act: kept beside the check, never passed to it."""
MIN_PRECISION = 0.9
MIN_SAMPLE = 50
"""What a rule must have shown in shadow before it may block (decision T22's
companion): precision measured on at least this many conversations."""


@dataclass(frozen=True)
class Change:
    """One thing a team's file changed in a rule it inherited: what an auditor reads."""

    rule: str
    field: str
    """A field name, or `(removed)` / `(added)`."""
    before: Any = None
    after: Any = None
    layer: str = "agent"


"""Where a rule runs inline: the moment, which tools, and what a fail does."""


class ConfigRefused(ValueError):
    """The configuration is wrong; nothing was built."""


def adapter_class(kind: str) -> type[Adapter]:
    try:
        module, cls = KINDS[kind].split(":")
    except KeyError:
        raise ConfigRefused(
            f"unknown adapter {kind!r}; known: {', '.join(sorted(KINDS))}"
        ) from None
    found = getattr(importlib.import_module(module), cls)
    assert isinstance(found, type) and issubclass(found, Adapter)
    return found


def load(path: str | Path, *, org: str | Path | None = None) -> dict[str, Adapter]:
    """The agent's checks, built. `org` names the organisation's policy file,
    laid between the preset and the agent's file."""
    return build(_read(path), org=_read(org) if org else None)


def changes(path: str | Path, *, org: str | Path | None = None) -> list[Change]:
    """Every change the agent's file makes to rules it inherited: for audit."""
    return layered(_read(path), _read(org) if org else None)[1]


def _read(path: str | Path) -> dict[str, Any]:
    loaded = yaml.safe_load(Path(path).read_text()) or {}
    return dict(loaded)


def build(config: Mapping[str, Any], *, org: Mapping[str, Any] | None = None) -> dict[str, Adapter]:
    """Every configured evaluator, built, by its configured name."""
    config = layered(config, org)[0]
    _only(config, frozenset({"judge", "evaluators", "spec", "moments"}), "the file")
    judge = _judge(config.get("judge"))
    built: dict[str, Adapter] = {}
    for name, spec in (config.get("evaluators") or {}).items():
        spec = dict(spec)
        cls = adapter_class(spec.pop("adapter", name))
        if cls.uses_judge and judge is None:
            raise ConfigRefused(f"{name!r} ({cls.kind}) needs a judge; none is configured")
        scale = _scale(spec.pop("scale", None), name)
        placement = {k: spec.pop(k) for k in PLACEMENT if k in spec}
        governance = {k: spec.pop(k) for k in GOVERNANCE if k in spec}
        try:
            built[name] = cls(name=name, judge=judge, scale=scale, **spec)
        except TypeError as wrong:
            raise ConfigRefused(f"{name!r} ({cls.kind}): {wrong}") from None
        built[name].placement = _placement(placement, name)
        built[name].governance = _governance(governance, built[name].placement, name)
    return built


def _governance(spec: Mapping[str, Any], placement: Mapping[str, Any], name: str) -> dict[str, Any]:
    """A rule may block only with an owner, and, unless the organisation locked
    it, with evidence from shadow: precision of at least `MIN_PRECISION` on at
    least `MIN_SAMPLE` conversations, and when it was measured."""
    if placement.get("mode") != "block":
        return dict(spec)
    if not spec.get("owner"):
        raise ConfigRefused(
            f"{name} can't block without an owner: add `owner:` (who answers for it)"
        )
    if spec.get("locked"):
        return dict(spec)
    evidence = spec.get("evidence") or {}
    precision, sample = evidence.get("precision"), evidence.get("sample")
    if precision is None or sample is None or not evidence.get("measured"):
        raise ConfigRefused(
            f"{name} can't block yet: give its evidence from shadow "
            f"(`evidence: {{precision, sample, measured}}`); until then use mode: shadow"
        )
    if float(precision) < MIN_PRECISION or int(sample) < MIN_SAMPLE:
        raise ConfigRefused(
            f"{name} can't block: precision {precision} on {sample} conversations; "
            f"blocking needs at least {MIN_PRECISION} on at least {MIN_SAMPLE}"
        )
    return dict(spec)


def load_hooks(path: str | Path, *, org: str | Path | None = None, on_record: Any = None) -> Hooks:
    """The rules a file places inline (`at:`), as hooks for a loop of your own.
    A rule placed in YAML starts in `shadow` unless the file says otherwise: it
    runs and is recorded, and acts only once someone moves it to `block`.

        moments:
          pre_tool: {budget_ms: 200, on_error: closed}
    """
    raw = layered(_read(path), _read(org) if org else None)[0]
    hooks = Hooks(moments=_moments(raw.get("moments") or {}), on_record=on_record)
    for name, check_ in load(path, org=org).items():
        where = check_.placement
        if where:
            hooks.add(
                where["at"],
                as_hook(check_, on_fail=where.get("on_fail", "block")),
                tools=where.get("tools", ()),
                side_effects=where.get("side_effects", ()),
                name=name,
                mode=where.get("mode", "shadow"),
                expected_ms=check_.expected_ms,
            )
    return hooks


def _moments(spec: Mapping[str, Any]) -> dict[str, Moment]:
    out: dict[str, Moment] = {}
    for position, settings in spec.items():
        if position not in POSITIONS:
            raise ConfigRefused(f"moments.{position}: not a moment; known: {', '.join(POSITIONS)}")
        _only(settings, frozenset({"budget_ms", "on_error"}), f"moments.{position}")
        if settings.get("on_error", "closed") not in ("closed", "open"):
            raise ConfigRefused(f"moments.{position}.on_error must be closed or open")
        out[position] = Moment(**settings)
    return out


def _placement(spec: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not spec:
        return {}
    if spec.get("at") not in POSITIONS:
        raise ConfigRefused(f"{name}.at must be one of {', '.join(POSITIONS)}")
    if spec.get("on_fail", "block") not in ("block", "escalate", "allow"):
        raise ConfigRefused(f"{name}.on_fail must be block, escalate or allow")
    if spec.get("mode", "shadow") not in MODES:
        raise ConfigRefused(f"{name}.mode must be one of {', '.join(MODES)}")
    if spec.get("tools") and spec["at"] not in ("pre_tool", "post_tool"):
        raise ConfigRefused(f"{name}.tools is for pre_tool and post_tool only")
    return {k: tuple(v) if isinstance(v, list) else v for k, v in spec.items()}


def layered(
    agent: Mapping[str, Any], org: Mapping[str, Any] | None = None
) -> tuple[dict[str, Any], list[Change]]:
    """The preset, then the organisation's policy, then the agent's file, each
    laid over the last field by field (`null` removes a rule). A rule the
    organisation marks `locked: true` can't be removed or changed by the agent's
    file. Returns the merged file and every change the agent's file made to a
    rule it inherited, for audit."""
    org = dict(org or {})
    agent = dict(agent)
    preset = agent.get("preset", org.get("preset"))
    base = with_preset({"preset": preset} if preset else {})
    evaluators = {k: dict(v) for k, v in (base.get("evaluators") or {}).items()}
    for key, spec in (org.get("evaluators") or {}).items():
        if spec is None:
            evaluators.pop(key, None)
        else:
            evaluators[key] = {**evaluators.get(key, {}), **spec}
    locked = {k for k, v in evaluators.items() if v.get("locked")}
    found: list[Change] = []
    for key, spec in (agent.get("evaluators") or {}).items():
        before = evaluators.get(key)
        if key in locked:
            assert before is not None
            if spec is None or any(before.get(f) != v for f, v in spec.items()):
                owner = before.get("owner", "the organisation")
                raise ConfigRefused(
                    f"{key} is locked by the organisation's policy; only its owner ({owner}) "
                    "can change it"
                )
            continue
        if spec is None:
            if before is not None:
                found.append(Change(key, "(removed)", before=dict(before)))
                evaluators.pop(key)
            continue
        if before is None:
            found.append(Change(key, "(added)", after=dict(spec)))
        else:
            found += [
                Change(key, f, before.get(f), v) for f, v in spec.items() if before.get(f) != v
            ]
        evaluators[key] = {**(before or {}), **spec}
    merged = {k: v for k, v in {**org, **agent}.items() if k not in ("preset", "evaluators")}
    merged["moments"] = {**(org.get("moments") or {}), **(agent.get("moments") or {})}
    if not merged["moments"]:
        merged.pop("moments")
    if "judge" not in merged and base.get("judge"):
        merged["judge"] = base["judge"]
    merged["evaluators"] = evaluators
    return merged, found


def with_preset(config: Mapping[str, Any]) -> dict[str, Any]:
    """The team's file laid over its preset: a check the team names replaces the
    preset's field by field; a check set to `null` is removed; the team's judge
    wins. Without `preset`, the file as it is."""
    config = dict(config)
    name = config.pop("preset", None)
    if name is None:
        return config
    path = PRESETS / f"{name}.yaml"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in PRESETS.glob("*.yaml")))
        raise ConfigRefused(f"unknown preset {name!r}; known: {known}")
    base = yaml.safe_load(path.read_text()) or {}
    evaluators = {k: dict(v) for k, v in (base.get("evaluators") or {}).items()}
    for key, spec in (config.get("evaluators") or {}).items():
        if spec is None:
            evaluators.pop(key, None)
        else:
            evaluators[key] = {**evaluators.get(key, {}), **spec}
    return {**base, **config, "evaluators": evaluators}


def _judge(spec: Mapping[str, Any] | None) -> JudgeModel | None:
    if spec is None:
        return None
    try:
        return JudgeModel(**spec)
    except TypeError as wrong:
        raise ConfigRefused(f"judge: {wrong}") from None


def _scale(spec: Mapping[str, Any] | None, name: str) -> Scale | None:
    if spec is None:
        return None
    _only(spec, SCALE_FIELDS, f"{name}.scale")
    scale = Scale(**spec)
    if scale.raw_max <= scale.raw_min:
        raise ConfigRefused(f"{name}.scale: raw_max must be above raw_min")
    return scale


def _only(found: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = set(found) - allowed
    if unknown:
        raise ConfigRefused(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
