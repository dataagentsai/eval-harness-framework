# Spike: can one data shape hold four eval providers?

**Date:** 17 Oct 2026. **Question:** the hardest part of the framework is making
our data classes, open-source classes and Azure's SDK fit together. Does
`agent_harness.evals.EvalRequest` / `EvalResult` survive contact with real SDKs?

**Answer: yes, with three additions to the result and one to the adapter.**
Four providers ran on the same five requests through one `EvalRequest`, and
every answer came back as one `Result`. 29 offline tests pass against the
recorded answers.

## What was run

| Check | Provider and version | Judge | Mode |
|---|---|---|---|
| Groundedness | `azure-ai-evaluation` 1.18.9 | Groq `openai/gpt-oss-120b` | online |
| Tool correctness | `deepeval` 4.3.1 | none (deterministic mode) | inline |
| Faithfulness | `ragas` 0.4.3 (`metrics.collections`) | Groq `openai/gpt-oss-120b` | online |
| PII | `presidio-analyzer` with `en_core_web_sm` | none | inline |

Azure's evaluator ran with no Azure account: it accepts any OpenAI-compatible
judge model, so the free Groq model FNOL already uses was the judge.

## Results (from `python -m spike.record`)

| Case | Azure | Ragas | DeepEval | Presidio |
|---|---|---|---|---|
| grounded reply | pass, 5/5 | pass, 1.0 | — | pass |
| ungrounded reply (invented ₹40,000) | fail, 2/5 | fail, 0.0 | — | pass |
| payout promised, `issue_payout` never called | — | — | fail, 0.5, finding `missing_tool: issue_payout` | pass |
| payout called | — | — | pass, 1.0 | pass |
| reply echoing name, phone, email | — | — | — | fail, 5 findings |

The Azure judge cost about $0.0005 per call, priced from the harness's own table.

## What the spike found

1. **The request shape held.** OpenAI-format messages and tools plus our
   `Passage` mapped into all four providers without changing `EvalRequest`.
2. **Every adapter splits into three parts.** `to_provider` and
   `from_provider` are pure functions tested offline against recorded answers.
   `call` is the only part that touches a vendor.
3. **`EvalResult` needs three additions** (`spike/canonical.py`):
   - `raw`: the provider's answer, untouched.
   - `findings`: one entry per hit, with its position in the text (Presidio
     returned 5).
   - `dropped`: what the mapping lost.
4. **`dropped` must be relative to what a check wants.** At first, Presidio was
   reported as dropping the query, which a PII check never needed. Adapters now
   declare `wants` beside `carries`.
5. **Confidence is not severity.** Presidio says how sure it is, not how bad
   the hit is. `Finding` holds both, and severity per kind is policy (YAML).
6. **Scores normalise from a declared `Scale`** (min, max, direction,
   threshold), so 1–5, 0–7 harm and 0–1 confidence all become 0–1 with 1 best.
7. **Every mapping into a provider lost something, and now says so:**
   - Azure joins passages into one string, so passage ids are lost.
   - Ragas's new API takes bare strings, so ids are lost there too. Its old API
     had room for them.
   - Our `ToolResult` has no call id, so results match calls only by tool name.
   - DeepEval compares tool names, not arguments.

## Surprises: the version churn the adapter layer must absorb

- **Ragas 0.4.3 would not import** with the newest `langchain-community`
  (0.4.2 removed a module it imports). Pinned to 0.4.1.
- **Ragas has two `Faithfulness` classes** with different inputs and different
  LLM wrappers. Its new one returns no reason and no token count, so its cost
  is unknown.
- **DeepEval's deterministic mode still demands an LLM key**, because it builds
  a model at construction. Handing it the tool definitions silently switches
  it to LLM grading, which changes its speed and cost.
- **Azure returns seven keys per metric** (`groundedness`, `_score`, `_passed`,
  `_result`, `_reason`, `_status`, `_threshold`, `_properties`), not the three
  commonly documented. Token counts are in `_properties`.
- **Presidio's defaults are US-centric.** It missed "Priya Sharma" (small
  model), called claim id "CLM-010003" a US driver's licence, read the +91
  phone number as both a phone and a date, and flagged the email address twice
  more as URLs. Use in India needs an entity list, India recognizers (PAN,
  Aadhaar) and overlap merging.
- One wrong belief caught by a test: I first read Azure's `_properties` as a
  string. It is a dict; my inspection script had stringified it.

## What this means for the design

- Keep the hub: our classes in the middle, one translator per provider.
- Add `raw`, `findings` (with confidence and severity) and `dropped` to `EvalResult`.
- Add `wants` and `carries` to the `Evaluator` port, beside `needs`.
- Put `Scale` and finding severity per kind in `evaluators.yaml`.
- One `Judge` setting, handed to each SDK in its own shape (`spike/judge.py`).
- Pin each provider's version in its adapter and re-record fixtures on upgrade.
- Not tested yet: multi-turn and session-level checks (the domain patterns),
  Azure content safety (needs an Azure project), LangSmith and App Insights as
  trace sources.

## Run it

```bash
uv venv --python 3.12 .venv && source .venv/bin/activate
# the hub classes, from the reference agent at the commit the spike ran against
uv pip install --no-deps "agent-harness @ git+https://github.com/dataagentsai/reference-agent@fe77def#subdirectory=packages/agent-harness"
uv pip install -r requirements-spike.txt
python -m pytest tests          # offline, against recorded answers
GROQ_API_KEY=... python -m spike.record   # live, re-records spike/fixtures/
```
