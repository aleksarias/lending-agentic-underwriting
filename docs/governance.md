# Governance

## Principals and grants (Unity Catalog, `lending_uw_dev`)
| Schema | harness SP | agent SP | promoter SP | you (owner) |
|---|---|---|---|---|
| raw | SELECT | — | — | owner |
| curated | ALL | SELECT on `applications_dev` (view), `data_catalog` | — | owner |
| labels | ALL | SELECT on `labels_active` (view: active definition, TRAIN only) | — | owner |
| feature_registry | ALL | read/write | — | owner |
| experiments | ALL | read/write | read + EXECUTE | owner |
| holdout | ALL (**only reader**) | — | — | owner |
| production | read + EXECUTE | — | ALL (**only writer**) | owner |
| ops | ALL | — | SELECT | owner |

Proven by `make test-integration` (13 checks against the live workspace).

**Enforced by the platform:** the table above. **Enforced in code (defense in depth):** the same spec in every
Store; SQL guard (single SELECT, allow-listed objects, 200-row cap); holdout token issued only by the gate; per-
cycle caps; agents have no tools for definition changes, approvals or promotion.

**Not enforced against you:** as catalog owner and workspace admin you can grant yourself anything, including holdout
access. Isolation is between the system's identities. In production, ownership should move to a group with change
control.

## Human-only actions
- `lau default-definition plan/apply` (interactive confirmation, or a recorded approval for the exact hash)
- `lau promote` (gate result shown, interactive approval with rationale → `ops.approvals`, then promoter SP)

## Audit
`ops.agent_trace` (every tool call: who, what, cost, inputs, outputs; credentials redacted; PII masked in prod),
`ops.pipeline_state`, `ops.definition_versions`, `ops.active_definition` (append-only), `ops.definition_approvals`,
`ops.evaluations`, `ops.experiment_counter`, `ops.gate_results`, `ops.approvals`, `production.promotions`,
`ops.cost_log`, `ops.alerts`, `ops.monitoring_runs`.

## Credentials
Only in `.env` (gitignored, mode 600). Never loaded into `os.environ`; passed to SDKs as explicit per-role configs.
`.env` holds: admin auth, `ANTHROPIC_API_KEY` (+ `ANTHROPIC_WORKSPACE_ID` if the key is org-level), and one OAuth
M2M pair per service principal (written by `lau init`). Jobs use the run_as identity natively and read agent/
Anthropic secrets from secret scope `lau` (not created automatically).
