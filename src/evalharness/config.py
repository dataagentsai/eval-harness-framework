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
from pathlib import Path
from typing import Any

import yaml

from evalharness.adapter import Adapter
from evalharness.adapters import ADAPTERS
from evalharness.core import Scale
from evalharness.hooks import POSITIONS, Hooks
from evalharness.hooks import check as as_hook
from evalharness.judge_model import JudgeModel
from evalharness.patterns import PATTERNS

KINDS = {**ADAPTERS, **PATTERNS}
"""Every buildable check: provider adapters and our domain patterns."""
PRESETS = Path(__file__).parent / "presets"

SCALE_FIELDS = frozenset({"raw_min", "raw_max", "higher_is_better", "threshold"})
PLACEMENT = ("at", "tools", "side_effects", "on_fail")
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


def load(path: str | Path) -> dict[str, Adapter]:
    return build(yaml.safe_load(Path(path).read_text()) or {})


def build(config: Mapping[str, Any]) -> dict[str, Adapter]:
    """Every configured evaluator, built, by its configured name."""
    config = with_preset(config)
    _only(config, frozenset({"judge", "evaluators", "spec"}), "the file")
    judge = _judge(config.get("judge"))
    built: dict[str, Adapter] = {}
    for name, spec in (config.get("evaluators") or {}).items():
        spec = dict(spec)
        cls = adapter_class(spec.pop("adapter", name))
        if cls.uses_judge and judge is None:
            raise ConfigRefused(f"{name!r} ({cls.kind}) needs a judge; none is configured")
        scale = _scale(spec.pop("scale", None), name)
        placement = {k: spec.pop(k) for k in PLACEMENT if k in spec}
        try:
            built[name] = cls(name=name, judge=judge, scale=scale, **spec)
        except TypeError as wrong:
            raise ConfigRefused(f"{name!r} ({cls.kind}): {wrong}") from None
        built[name].placement = _placement(placement, name)
    return built


def load_hooks(path: str | Path) -> Hooks:
    """The rules a file places inline (`at:`), as hooks for a loop of your own."""
    hooks = Hooks()
    for name, check_ in load(path).items():
        where = check_.placement
        if where:
            hooks.add(
                where["at"],
                as_hook(check_, on_fail=where.get("on_fail", "block")),
                tools=where.get("tools", ()),
                side_effects=where.get("side_effects", ()),
                name=name,
            )
    return hooks


def _placement(spec: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not spec:
        return {}
    if spec.get("at") not in POSITIONS:
        raise ConfigRefused(f"{name}.at must be one of {', '.join(POSITIONS)}")
    if spec.get("on_fail", "block") not in ("block", "escalate", "allow"):
        raise ConfigRefused(f"{name}.on_fail must be block, escalate or allow")
    if spec.get("tools") and spec["at"] not in ("pre_tool", "post_tool"):
        raise ConfigRefused(f"{name}.tools is for pre_tool and post_tool only")
    return {k: tuple(v) if isinstance(v, list) else v for k, v in spec.items()}


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
