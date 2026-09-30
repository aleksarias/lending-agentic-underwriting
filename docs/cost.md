# Cost guardrails

| Cap | Default | Where enforced |
|---|---|---|
| Databricks per cycle | 5 DBU (estimate) | `cost.check_cycle_caps` before a cycle |
| Anthropic per cycle | $10 | per-agent `max_budget_usd` = min(role cap, remaining); spend charged to the cycle |
| Per-agent | turns, $, minutes | `config/budgets.yaml` → `ClaudeAgentOptions` + `asyncio.wait_for` |
| Experiments per cycle | 20 | `evaluate_candidate` tool refuses beyond the cap |
| Critique rounds | 2 | orchestrator loop |
| Wall clock per cycle | 60 min | runner refuses to start agents past the deadline |
| Monthly hard stop | $100 | `cost.check_monthly_cap` on apply and run-cycle (from `ops.cost_log`) |
| Holdout uses | 5 gate runs / definition | `harness.gate` |

Prices: SQL Serverless on AWS Premium is $0.70/DBU (current list, checked 2026-09-30), and a 2X-Small warehouse uses 4 DBU/h
= $2.80 per running hour. Busy-time metering is a lower bound, because billing is by uptime including idle time and the auto-stop tail.

Estimates print in `default-definition plan` and `run-cycle`; actuals: Anthropic from
`ResultMessage.total_cost_usd`, Databricks metered per query (+ auto-stop tail) and, with a few hours' lag, from
`system.billing.usage` via `lau cost`. Compute: one 2X-Small serverless warehouse, 5-minute auto-stop; jobs deployed
paused.
