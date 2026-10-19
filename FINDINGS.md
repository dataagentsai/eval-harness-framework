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

---

# Run 3: the clothing agent, and the examples checked against each spec (18 Oct 2026)

`scripts/patterns_on_scenarios.py` over the reference agent's 49 scenarios: 141
turns, 85 conversations. As with FNOL, every scenario passes the agent's own
gates, so each finding was traced to its cause, this time against the agent's
spec (`clean-ai-engineering/drafts/examples/support-agent.aoas.yaml`).

| Finding | Cause | Fixed where |
|---|---|---|
| Approval asked for a ₹4,999 refund, "with no rule calling for it" | The example had half the rule. The spec lets the agent refund alone only a **returned** order of at most ₹10,000; a delivered order needs a person whatever its total. | `result_of` conditions gained `in` and `not_in`; the example now says both halves. |
| "No hand-over although 3 tool calls failed" | Two mistakes of ours. The spec's trigger is **2 failures in a row** (`tool-unavailable`); "three failed attempts" is listed as *deferred*. And failures before a person hands the conversation back do not count: that is what the scenario tests, and the agent is right. | `decision_vs_should` is judged **per window** (the steps since the previous such decision) and gained `consecutive_failed_at_least`. |
| The router's hand-over was not seen | A turn the router escalated by rule has `result: escalated` and no termination | `agent_harness.watch.sessions` records it as `awaiting_human` (reference-agent). |
| "Cancelled without looking the order up" | A rule of ours, not the spec's: the order system enforces cancel's preconditions | Removed from the example; a team may add it as its own policy. |
| FNOL: "no hand-over although the user said *was hurt*" | "Nobody was hurt" | The negation guard now reads the customer's words too (`user_says`), and knows "nobody" and "no one". |

**A rule about rules came out of this:** a hand-over pattern that lists only some
of the spec's triggers can judge only a *missed* hand-over. A hand-over for a
reason it doesn't list would look needless. So `decision_vs_should` takes
`check: under`, and both examples use it, since each lists 3 of its spec's 10
triggers.

**Result:** all checks pass on both agents with nothing left to explain. On the
clothing agent: 85 conversations judged for approvals and hand-overs, 3 refund
promises, 10 conversations stating order ids or amounts. FNOL's example gained the
same correction (2 failures in a row, not 3 in all) and still passes on all 48.

**What the three runs together say:** of every finding on two agents, one was a
real defect (FNOL's payouts missing from the conversation's trace, now fixed).
All the others were ours: the patterns' first versions (negation, windows,
customer facts) and examples written from guesses instead of from each agent's
spec. The second lesson is the more useful one for adoption: **write a domain's
rules from its spec, and say which part of the spec a rule covers.**

---

# Run 4: sessions from a third-party agent's own traces (18 Oct 2026)

`scripts/record_genai_traces.py` runs a small Pydantic AI 2.54 refund agent with
a scripted model (no model is called) and Pydantic AI's built-in
instrumentation, and writes its spans as OTLP JSON
(`tests/fixtures/otlp/pydantic_ai_refunds.jsonl`): 16 spans, 3 conversations, 4
agent runs. `evalharness.traces` reads the file and rebuilds each conversation
as a `Session` from the OpenTelemetry GenAI conventions alone, with no code on
the agent's side. `requires_before` then fails the conversation that refunds
without looking the order up, and passes the other two.

| What we saw | What the reader does |
|---|---|
| Each agent run is its own trace; `gen_ai.conversation.id` joins them | Groups by `gen_ai.conversation.id`, then `session.id`, then the trace id |
| Every `chat` span resends the whole history in `gen_ai.input.messages` | Takes only the user's words after the model last spoke, once per trace |
| Pydantic AI sends tool results back as `role: user` with no text part (the conventions' example uses `role: tool`) | A user message with no text part is not a user turn |
| A tool call appears twice: as a `tool_call` part in the output, and as an `execute_tool` span with the result | One step per call id; a result comes from the `execute_tool` span, or from a `tool_call_response` part when there is no tool span |
| A failed tool has status code 2 and the retry message as its result | `is_error` from the status |

**Gap in the conventions.** They have no attribute for a decision such as a
hand-over, or for how a conversation ended. Sessions rebuilt from GenAI spans
carry neither, so `decision_vs_should` cannot run on them until a team maps its
own attribute (as reference-agent records `termination`). This is one more item
for the proposal to the GenAI conventions group (Tier 11).

The GenAI conventions now live in their own repository
(open-telemetry/semantic-conventions-genai) and are all still `development`.

---

# Run 4b: a deployed agent's real traces, from App Insights (19 Oct 2026)

`evalharness.sources.app_insights` read FNOL's deployed traces from its App
Insights workspace (read-only; only spans named `agent.*` and `gen_ai.*`, so
HTTP spans and the URLs in them stay in Azure). `scripts/pull_app_insights.py`
wrote them to an OTLP file; `scripts/checks_on_traces.py` rebuilt the turns with
FNOL's own reader (`agent_harness.watch`, new `record.from_trace_spans`) and
ran the FNOL rules and the saved questions. Counts: `docs/runs/fnol-app-insights-2026-10-19.json`.

What was there: 688 spans, 39 turns over 13–14 Oct from one test user. **No
turn had content** (`agent.captured = False`: no customer words, no reply, no
tool arguments or results) and **none had a conversation id** (the deployed
build predates T14).

**What it exposed.** The first run reported two over-escalations: approvals
"with no rule calling for it". Both were false: the rule needs the claim's
approved amount, which was not recorded, and read its absence as "not over
₹25,000". The hand-over rule likewise passed turns whose words it never saw.

**Fix:** `Session.unrecorded` names what the source did not record (`text`,
`arguments`, `results`); the harness and the GenAI reader both set it. Each
condition evaluates to yes, no or unknown, and is unknown when it needs
unrecorded data that could have changed the answer (a tool result only if the
tool ran and succeeded; arguments only if the tool was called; words always).
A check that judged nothing because of it returns `skip: could not judge …`;
a partly judged one says how many items it could not judge. Structural
conditions (failures in a row, a payout with no claim read at all) are still
judged.

After the fix: no false findings; 5 hand-over checks judged from structure;
everything needing words or values is an explicit skip.

**Product consequence.** With privacy on, traces show what happened, not what
was said. Content checks must run where the content is (inside the agent's
environment, inline or right after the turn) and send only verdicts out.

---

# Run 5: verdicts back into App Insights, words kept inside (19 Oct 2026)

Decision T30: checks that need the conversation's words run inside the agent's
environment; only verdicts go to App Insights. `evalharness.sinks.otel_events`
writes each verdict as an OpenTelemetry `gen_ai.evaluation.result` event
through the logs API, so it goes wherever the agent's telemetry goes, beside
the judged turn's trace (`OperationId`).

`scripts/patterns_on_scenarios.py --emit-to-app-insights` ran FNOL's 29
scenarios in FNOL's environment (content present in process) and sent 240
verdicts, marked `evalharness.synthetic`, to the dev App Insights. Counted
back with KQL: `docs/runs/fnol-verdicts-app-insights-2026-10-19.json`.

What the round trip taught:

| Seen | Fix |
|---|---|
| App Insights stores an array attribute as Python-looking text (`('AAC-0029',)`) | Lists go as comma-separated text |
| "Nothing to check" counted as a pass inflates every report (a payout rule on 44 conversations with no payout) | The event's label is `not_applicable`; the framework's own verdict is unchanged |
| A finding's label can quote what was said or an amount; another provider's reason is model text about the conversation | Content-free explanation by default: our checks' counts and finding kinds; outside providers' verdict and kinds only |

Saved questions compile to KQL from their one definition (`questions.to_kql`).
With one deliberate failing verdict sent, `under_escalations` returned exactly
that row and the other questions none.
