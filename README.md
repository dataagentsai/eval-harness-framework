# Eval Harness Framework

A reusable, vendor-neutral framework for checking AI agents: quality evals,
security guardrails, cost rules and domain rules, behind one set of ports, with
any provider's checks mixed in one run and one result format.

It does not bring its own database, UI or dashboards. It reads from and writes
to the tools a team already uses (OpenTelemetry, LangSmith, Langfuse, App
Insights, Prometheus/Grafana) and ships content for them: checks, rule
templates, dashboard templates and metric definitions.

**Plan:** [docs/PLAN.html](docs/PLAN.html), the single page for tiers, todos, architecture and the supported-tools list.

**Status: spike.** The first question was whether one data shape can hold
several providers' checks. Azure AI Evaluation, DeepEval, Ragas and Presidio
were run through one request shape; see [FINDINGS.md](FINDINGS.md).

The data classes come from `agent_harness.evals` in
[reference-agent](https://github.com/dataagentsai/reference-agent).

Licensed under Apache-2.0.
