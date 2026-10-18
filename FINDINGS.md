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

---

# Run 2: the domain patterns on FNOL's own conversations (18 Oct 2026)

**Question:** do the five patterns find anything real in real conversations?

**How:** `scripts/patterns_on_scenarios.py` drove FNOL's 29 behaviour scenarios
through AgentTwin with tracing on (scripted model, no network). The harness
rebuilt 52 turns from the spans and grouped them into 48 conversations
(`agent_harness.watch.sessions`). `examples/claims-fnol.yaml` judged them. All 29
scenarios pass FNOL's own gates, so every finding was traced to its cause.

## What the first run found, and why

| Finding | Cause | Fixed where |
|---|---|---|
| The example used `same: [claim_id]` and a limit on `issue_payout.amount` | Guessed tool shapes. FNOL's tools take `id`; the amount is on the claim (`get_claim` → `approved_amount`), and the ₹25,000 limit is an approval decision, not an argument. | Example rewritten to the real names. `decision_vs_should` gained `result_of` and `all:` conditions to say "approval exactly when a payout is requested on a claim over ₹25,000". |
| 3 of 3 "promised but not done" findings | Negation: "Nothing has been paid yet", "neither has been paid yet" | `claim_needs_action` now skips a sentence that is a question or carries a negation word. 3 → 0 false alarms. |
| Claim ids "not from any system" | The agent repeated the id the customer typed | `consistency` counts the customer's own words as known (`from_user`, default on). |
| No conversation matched the payout phrases | The example's wording was not FNOL's | Phrases taken from FNOL's real replies ("has been issued", "has been made to the account"). |

## What remains: one real gap in FNOL's traces

After those fixes, all 7 remaining findings have one cause, and it is not in the
patterns: **a payout is not on the conversation's trace.**

- The model's `request_payout` is recorded as span `agent.tool.local`, which the
  turn rebuilder (`watch.record`, which reads `agent.tool`) does not read.
- The approval workflow's claim lookup, its decision (`agent.approval.assess`) and
  the payout itself (`agent.approval.carry_out` → `issue_payout`) each start a
  new trace, with nothing linking them to the conversation.

So a check that reads the conversation, ours or Langfuse's, cannot see money
move: the payout that happened looks like a promise not kept (3 findings), its
amount looks invented (3), and the approval looks unasked-for (1). FNOL's gates did
not catch this because they check the claims system's records, not the traces.
This is the context-propagation lesson from OpenTelemetry, met in practice.

**Fixed in the harness (18 Oct, reference-agent c10d572, claims-fnol-azure e9ce5ea),
on the owner's decision (D14):**

- `telemetry.work_scope(session_id, key)`: work done outside a turn for a
  conversation stamps its `session.id` on every span it opens, and decides
  capture as a turn does. The span contract declares `session.id` as allowed
  anywhere. The contract test caught the first attempt, which put it on spans
  that had not declared it.
- Local tools (`request_payout`) record side effect, outcome, arguments and
  result, as MCP tools do.
- The turn rebuilder reads local tool spans, and `record.background()` reads the
  work done outside turns. `watch.sessions` merges it in where it happened:
  inside a turn, before its reply (a payout within the limit is made while
  `request_payout` runs); between turns otherwise (a payout a person approved).
- FNOL's payout approval and the reference agent's refund approval run their
  assessment and carrying out in `work_scope`.

**After the fix, all five patterns pass on all 29 scenarios, with nothing
left to explain.** They now have real material: 4 payouts for "never pay a
claim nobody has read", 48 conversations for approvals and hand-offs, 2 kept
promises, and 17 conversations stating claim ids or amounts. A first version
of the merge put in-turn work after the reply, which made a payout look
announced before it was made; placing it by time window fixed that.

Suites: reference-agent 2,107 passed with the same 2 earlier failures; FNOL 755
passed.
