"""The catalog, requirement and decision data for the pages, read at build time
from where it already lives. Nothing here is typed in by hand except the list
of integrations, which is the plan's binding table in data form.

- AI Assurance Catalog (~/ai-assurance-catalog): 118 obligations, the
  archetypes, and the detection patterns.
- The 36 LLM cost rules (~/DataAgents.ai/56 and 61), and which of them are
  built (~/llm-cost-explainer/src/lce/rules/llm_*.yaml).
- The agents' specs (~/clean-ai-engineering/drafts/examples/*.aoas.yaml).
- The decisions table in docs/PLAN.html.
"""

import glob
import html
import re
from pathlib import Path

import live
import yaml

from evalharness.config import KINDS, adapter_class, load
from evalharness.requirements import requirement

HOME = Path.home()
AAC = HOME / "ai-assurance-catalog"
NOTES = HOME / "DataAgents.ai"
LCE_RULES = HOME / "llm-cost-explainer" / "src" / "lce" / "rules"
SPECS = HOME / "clean-ai-engineering" / "drafts" / "examples"
MISSING = live.MISSING


def _yaml(path):
    try:
        return yaml.safe_load(Path(path).read_text())
    except FileNotFoundError:
        MISSING.append(str(path))
        return None


# --------------------------------------------------------------- the standard

def obligations():
    out = []
    for f in sorted(glob.glob(str(AAC / "catalog" / "AAC-*.yaml"))):
        d = _yaml(f)
        out.append(dict(id=d["id"], level=d.get("level", ""), dimension=d.get("dimension", ""),
                        core=bool(d.get("core")), archetypes=d.get("archetypes", []),
                        title=" ".join(d["title"].split()), statement=" ".join(d["statement"].split())))
    if not out:
        MISSING.append(str(AAC / "catalog"))
    return out


def archetypes():
    d = _yaml(AAC / "taxonomy" / "archetypes.yaml") or {}
    return {a["id"]: a for a in d.get("archetypes", [])}


def detection_patterns():
    out = []
    for f in sorted(glob.glob(str(AAC / "patterns" / "*.yaml"))):
        d = _yaml(f)
        for p in d.get("patterns", []):
            out.append(dict(id=p["id"], name=p["name"], domain=d.get("domain", Path(f).stem),
                            archetypes=p.get("archetypes", []), caught_by=p.get("caught_by", []),
                            symptom=" ".join(str(p.get("symptom", "")).split())))
    return out


# ----------------------------------------------------------------- cost rules

def cost_rules():
    titles = {}
    for name in ("56-llm-cost-explainer.md", "61-llm-cost-analyse-design.md", "57-llm-cost-explainer-design.md"):
        path = NOTES / name
        if not path.is_file():
            MISSING.append(str(path))
            continue
        for m in re.finditer(r"^\| *LLM-(\d\d) *\| *(.+?) *\|", path.read_text(), re.M):
            title = re.sub(r"\*\*", "", m.group(2))
            title = re.sub(r"\s*\(.*?\)\s*", " ", title).strip()
            titles.setdefault(f"LLM-{m.group(1)}", title)
    built = {f"LLM-{Path(f).stem[4:]}" for f in glob.glob(str(LCE_RULES / "llm_*.yaml"))}
    return [dict(id=i, title=titles[i], built=i in built) for i in sorted(titles)]


# -------------------------------------------------------- our checks, linked

def checks():
    """Every check this framework can run: kind, provider, obligations, speed."""
    out = []
    for kind in sorted(KINDS):
        cls = adapter_class(kind)
        out.append(dict(kind=kind, provider=cls.provider, obligations=cls.obligations,
                        speed=cls.speed, ms=cls.expected_ms))
    return out


def checked_by():
    """{AAC id: [check kinds that help discharge it]}."""
    found = {}
    for c in checks():
        for oid in c["obligations"]:
            found.setdefault(oid, []).append(c["kind"])
    return found


# ----------------------------------------------------- domain requirements

AGENTS = [
    dict(id="fnol", name="Motor-claims FNOL agent", example="claims-fnol.yaml"),
    dict(id="clothing", name="Clothing shop support agent", example="support-agent-clothing.yaml"),
]


def spec_requirements(spec):
    """Every requirement id the spec defines, with its wording, in spec order."""
    out = []
    policies = (spec or {}).get("policies") or {}
    for key, value in policies.items():
        if isinstance(value, dict) and "rule" in value:
            out.append((key, value["rule"], value.get("concern", "")))
        elif isinstance(value, dict):
            for s in value.get("statements") or ():
                out.append((s["id"], s["rule"], s.get("concern", "")))
            if key == "escalation":
                for kind in ("on_request", "on_reply", "on_condition"):
                    for t in value.get(kind) or ():
                        rid = f"escalation.{t['id']}"
                        out.append((rid, requirement(spec, rid), "hand-over"))
        elif key != "escalation":
            out.append((key, requirement(spec, key), "privacy"))
    for op, body in ((spec or {}).get("operations") or {}).items():
        if isinstance(body, dict) and isinstance(body.get("authority"), dict) and "agent_when" in body["authority"]:
            rid = f"{op}.authority.agent_when"
            out.append((rid, f"the agent may do {op} alone only when: {requirement(spec, rid)}", "authority"))
    return out


def agent_trace(agent):
    """(rules, requirements) for one example agent: each rule with the ids it
    names; each requirement with its wording and the rules that test it."""
    path = live.ROOT / "examples" / agent["example"]
    config = yaml.safe_load(path.read_text())
    spec = _yaml(SPECS / Path(config["spec"]).name)
    built = load(path)
    rules = [dict(name=n, kind=c.kind, description=c.description, requirements=c.requirements,
                  obligations=c.obligations) for n, c in built.items()]
    tested = {}
    for r in rules:
        for rid in r["requirements"]:
            tested.setdefault(rid, []).append(r["name"])
    reqs = [dict(id=rid, text=text, concern=concern, rules=tested.get(rid, []))
            for rid, text, concern in spec_requirements(spec)]
    return rules, reqs


# -------------------------------------------------------------- decisions

def decisions():
    """The taken decisions (T#) from docs/PLAN.html, as (id, decision, why, date)."""
    text = (live.ROOT / "docs" / "PLAN.html").read_text()
    out = []
    for m in re.finditer(r"<tr><td>(T\d+)</td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>", text):
        out.append(tuple(m.groups()))
    return out


def strip(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s))


# ----------------------------------------------------------- integrations
# The plan's binding table as data: where we read from, what we call, where
# we write to, and who calls us inline. `state` is "built" or the tier.

INTEGRATIONS = [
    # side, name, family, state
    ("source", "OTLP file (Collector)", "open", "built"),
    ("source", "Phoenix", "open", "Tier 4"),
    ("source", "App Insights (KQL)", "azure", "built"),
    ("source", "Langfuse", "open", "Tier 4"),
    ("source", "LangSmith runs", "saas", "Tier 8"),
    ("source", "Promptfoo results", "open", "Tier 7"),
    ("source", "Usage exports (cost)", "any", "Tier 5"),
    ("source", "CloudWatch / X-Ray", "aws", "later"),
    ("source", "Cloud Trace", "gcp", "later"),
    ("check", "Presidio (PII)", "open", "built"),
    ("check", "Azure AI Evaluation", "azure", "built"),
    ("check", "DeepEval", "open", "built"),
    ("check", "Ragas", "open", "built"),
    ("check", "Judge model (any)", "any", "built"),
    ("check", "Our five patterns", "open", "built"),
    ("check", "Azure Content Safety", "azure", "Tier 6"),
    ("check", "Prompt Guard 2 · safeguard", "open", "Tier 6"),
    ("check", "Bedrock Guardrails", "aws", "later"),
    ("check", "Cost rules (36)", "open", "Tier 5"),
    ("host", "Reference agent harness", "open", "built"),
    ("host", "Pydantic AI hooks", "open", "Tier 7"),
    ("host", "LangGraph hooks", "open", "Tier 7"),
    ("host", "LiteLLM guardrail (gateway)", "open", "Tier 7"),
    ("host", "Decorators (no framework)", "open", "Tier 7"),
    ("host", "CI step (GitHub, Azure DevOps)", "any", "Tier 7"),
    ("sink", "OTel gen_ai.evaluation.result", "open", "Tier 4"),
    ("sink", "Langfuse / Phoenix scores", "open", "Tier 4"),
    ("sink", "App Insights events", "azure", "Tier 8"),
    ("sink", "Prometheus + Grafana", "open", "Tier 8"),
    ("sink", "LangSmith feedback", "saas", "Tier 8"),
    ("sink", "Alerts: Teams, ServiceNow", "any", "Tier 8"),
    ("sink", "Cube / Metric Views + MCP", "open", "Tier 9"),
]

FAMILY = {"open": "Open source", "azure": "Azure", "aws": "AWS", "gcp": "Google Cloud",
          "saas": "SaaS", "any": "Any stack"}
