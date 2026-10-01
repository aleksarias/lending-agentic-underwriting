# Underwriting Console — API and data contract

Response shapes: `console/web/src/api/types.ts` (source of truth). Backend: `src/lau/console/` (FastAPI).
Front end: `console/web/` (React + Vite). The console reads **only** through the read-only `ui` store role
(`get_store("ui")`): schema SELECT on `ops`, `experiments`, `feature_registry`, `production`; table SELECT on
`curated.data_catalog`, `curated.field_lineage`, `labels.split_meta`. It never reads raw applicant rows, all-version
labels (`labels.labels_all`), `curated.applications`, `curated.cashflow_monthly` or `holdout`. Anything needing those
is precomputed by the harness into aggregate `ops.*` tables (see "New tables").

Local/offline: `LAU_BACKEND=local LAU_LOCAL_LAKE=<fixture lake>` reads a DuckDB copy of those tables
(`scripts/export_console_fixture.py`). Actions (POST endpoints) are disabled unless `LAU_CONSOLE_ACTIONS=1`; when
enabled they call the existing `lau` code paths (harness/promoter identities from `.env`) and are logged with the
requesting user (`X-Forwarded-Email` on Databricks Apps, OS user locally).

## Front-end routes

| Route | Page file | Screen |
|---|---|---|
| `/` | `Overview.tsx` | 1 Overview |
| `/activity` | `Activity.tsx` | 2 Live activity (research) |
| `/decisions` | `Decisions.tsx` | 3 Decisions (live API) |
| `/progress` | `Progress.tsx` | 4 Progress: is it improving? |
| `/history`, `/history/cycles/:cycleId`, `/history/compare` | `History.tsx`, `CycleDetail.tsx`, `Compare.tsx` | 5 History and change log |
| `/definitions`, `/definitions/:version` | `Definitions.tsx`, `DefinitionDetail.tsx` | 6 Definitions over time |
| `/upcoming` | `Upcoming.tsx` | 7 Upcoming |
| `/models`, `/models/:name/:version` | `Models.tsx`, `ModelDetail.tsx` | 8 Models |
| `/performance`, `/performance/evaluations/:evalId` | `Performance.tsx`, `EvaluationDetail.tsx` | 9 Performance |
| `/fairness` | `Fairness.tsx` | 10 Fairness and compliance |
| `/feed` | `Feed.tsx` | 11 Loan status feed |
| `/data`, `/data/:variable` | `Data.tsx`, `VariableDetail.tsx` | 12 Data catalog and cash flows |
| `/features` | `Features.tsx` | 13 Features lab |
| `/agents`, `/agents/reports/:reportId`, `/agents/lessons` | `Agents.tsx`, `ReportDetail.tsx`, `Lessons.tsx` | 14 Agents |
| `/approvals`, `/approvals/:candidateRef` | `Approvals.tsx`, `ApprovalDetail.tsx` | 15 Approvals |
| `/rollouts` | `Rollouts.tsx` | 16 Rollouts and rollback |
| `/shadow` | `Shadow.tsx` | 17 Shadow scoring |
| `/alerts` | `Alerts.tsx` | 18 Alerts and service levels |
| `/cost` | `Cost.tsx` | 19 Cost |
| `/settings` | `Settings.tsx` | 20 Reports and settings |

`candidateRef` in routes is URL-encoded (e.g. `candidate%3A11`). Model routes use the registered model name as
stored (`pd_candidates` locally, `lending_uw_dev.experiments.pd_candidates` on Databricks), URL-encoded.

## Endpoints

All under `/api`. GET unless stated. Query params in brackets are optional. "def" = definition_version or a unique
prefix such as the 8-character short form (defaults to the active definition). Errors: 400 for malformed ids, 404 for
unknown ones, 403 for actions while disabled, all as `{"detail": "..."}`. Responses never contain NaN (null instead).

| Method, path | Response type | Reads | Notes |
|---|---|---|---|
| `/notifications` | `Unavailable \| NotificationsInfo` | the mirror's notification log | desktop notifications run only in mirror mode |
| `/status` | `StatusSummary` (with `snapshot`: mode mirror/direct/fixture, published and synced times) | ops.active_definition, definition_versions, model_registry, improvement_ledger, cycles, cycle_heartbeat, cost_log, approvals/gate_results/evaluations (for waiting), alerts, config/default_definition.yaml | cached 10 s |
| `/overview` | `OverviewData` | as status + events + pipeline_state | status sentence is deterministic text, no LLM |
| `/activity` | `ActivityData` | cycles, cycle_heartbeat, cycle_control, agent_trace, pipeline_state, config budgets | poll every 5 s; during an agent run the orchestrator writes a heartbeat and flushes the trace every 60 s |
| `/activity/trace?cycle_id&[after]` | `TraceEntry[]` | agent_trace | incremental |
| POST `/activity/stop` `{cycle_id, reason}` | `ActionResult` | writes ops.cycle_control (harness store) | actions only |
| `/decisions` | `DecisionsData` (`available`/`reason`; 30-day `totals`, `shares`, `daily`, `paths`, `bands`, `reasons` on declines, `versions`, 50 `recent`; `latency` (model-side and the latest load check); `policy`; `api`: state endpoint / endpoint_not_ready / in_process / not_built / no_policy, live build, gaps, release checks) | ops.decisions (test traffic excluded), ops.decision_builds, ops.release_checks, ops.active_policy, ops.policy_versions, ops.policy_approvals, production.rollouts, model_registry, extras/decision_api.json (mirror) | unavailable `reason` names the next step (approve a policy, build, send traffic) |
| `/decisions/search?q` | `{results: DecisionRow[]}` | ops.decisions | prefix of decision id or application id; at least 3 characters |
| `/decisions/{decision_id}` | `DecisionDetail` | ops.decisions | reasons with the model input behind each (reviewers), notice content, versions, shadow score; never applicant inputs; 404 unknown |
| `/decisions/{decision_id}/adverse-action` | `{decision_id, application_id, decision, decided_at, path, notice_required, principal_reasons[{rank, code, statement}], versions, caveat}` | ops.decisions | statements only, no feature names; counsel approves the notice itself |
| `/progress` | `ProgressData` (`production`: matured-loan evidence overall, by deciding model, band and vintage, or Unavailable) | improvement_ledger, benchmark_results, evaluations, experiment_counter, gate_results, cycles, cost_log, model_registry, harness_reference, production_evidence | |
| `/events?[types]&[definition]&[before]&[limit=100]` | `EventsPage` (ids unique; `next_before` is an opaque `timestamp~id` cursor to pass back as `before`, so ties at a page boundary are neither lost nor repeated; unknown definition 404) | assembled in Python from: active_definition, data_version, pipeline_state, cycles, evaluations, gate_results, approvals, definition_approvals, production.promotions, alerts, config_versions, experiments.reports, benchmark_results | newest first |
| `/changes?from&to` | `ChangeSet` | active_definition/definition_versions, model_registry, config_versions, data_version, events | version-vector diff between two instants |
| `/cycles` | `CycleSummary[]` | cycles | |
| `/cycles/{cycle_id}` | `CycleDetail` | cycles, agent_trace, experiments.reports; cycle_report.md from `reports/cycles/<id>/` if present | |
| `/lineage/{model_name}/{version}` | `LineageGraph` | model_registry, evaluations, gate_results, approvals, promotions, data_version, definition_versions, feature_registry.features | |
| `/definitions` | `DefinitionVersion[]` (with `summary`, `dpd`, `timing`, `window_months`) | definition_versions, active_definition, label_stats, labels.split_meta | newest first |
| `/definitions/{version}` | `DefinitionVersion` | same | |
| `/definitions/sensitivity` | `SensitivityData` | ops.definition_sensitivity | |
| `/pipeline?[def]` | `PipelineData` (unknown def 404) | pipeline_state (fingerprint freshness via lau.pipeline.stages.build_pipeline plan when possible, else latest status) | |
| `/upcoming` | `UpcomingData` (`next_plan` is the latest plan, already run, with `next_plan_cycle_id`; `backlog` = proposed features no model has used yet plus lessons awaiting re-verification under the active definition) | cycle_queue, improvement_ledger (denominator), gate_results, cost_log, agent_trace (latest submit_plan), feature_registry.features (proposed), resources/jobs.yml | `jobs` are the schedules declared in the Asset Bundle (deployed paused; the console identity has no Jobs API permission), so `next_run_at`/`last_*` are null |
| `/models` | `ModelVersion[]` | ops.model_registry, evaluations | |
| `/models/{name}/{version}` | `ModelCard` | model_registry, evaluations, gate_results, experiments.reports, approvals, feature_registry.features, benchmark_results | |
| `/performance?[def]` | `PerformanceData` | evaluations, gate_results, definition_versions, experiment_counter | `tests_since_reset` and `next_margin` for the selected definition; unknown def 404 |
| `/evaluations/{eval_id}` | `EvaluationDetail` | evaluations.result_json | also `proxy_detail`, `prohibited_features_used`, `best_known` and `versions` as the harness stored them, fairness `n` and mean PD per group (group sizes are not stored) |
| `/fairness?[def]` | `FairnessData` (unknown def 404; `decisions`: rates and adverse impact ratios on actual decisions, estimated groups next to the synthetic truth) | evaluations (fairness), ops.proxy_scan, ops.decision_fairness, config protected_classes/thresholds, experiments.reports (kind=compliance) | |
| `/feed` | `FeedData` (`servicer`: files read, quarantine by reason, restatements, monthly book by status, maturation; null before the first feed) | ops.feed_files, ops.feed_quarantine, ops.feed_restatements, ops.feed_summary, ops.maturation_events, ops.data_version, ops.vintage_curves, ops.label_stats | aggregates and file-level records only: the loan book is in curated |
| `/parity` | `Unavailable \| ParityData` | ops.serving_parity (latest run) | PSI, null rates and means, training against the last 30 days of decisions |
| `/catalog?[def]` | `CatalogData` (unknown def 404) | curated.data_catalog, curated.field_lineage | |
| `/catalog/{variable}?[def]` | `CatalogVariable` | same | |
| `/cashflow/cohorts` | `CashflowCohorts` | ops.cashflow_cohorts | |
| `/features` | `FeatureRow[]` | feature_registry.features, feature_performance, evaluations (usage via model features) | |
| `/agents` | `AgentInfo[]` | config models/budgets, prompt files (sha256[:12]), agent tool lists, agent_trace | |
| `/reports?[kind]&[cycle_id]&[candidate_ref]` | `ReportMeta[]` | experiments.reports | |
| `/reports/{report_id}` | `Report` | experiments.reports | body is agent-written markdown (render sanitized) |
| `/lessons` | `LessonsData` | LESSONS.md (lau.agents.lessons.read_lessons) | |
| `/approvals` | `ApprovalsData` | evaluations, experiments.reports, gate_results, approvals, definition_approvals, model_registry | pending = candidates **of the active definition** that passed validation, have red-team and compliance reports, and no decision yet; plus a definition_change item when config/default_definition.yaml differs from the active definition |
| `/approvals/{candidate_ref}` | `EvidencePacket` | evaluations, benchmark_results, gate_results, reports, cycles, approvals, production.promotions | `beats_best_known` from benchmark_results; also the recorded `decision`, the `promotion` and the definition's `holdout` budget; model names resolve to the registry mirror's (full Unity Catalog) names |
| POST `/approvals/{candidate_ref}/gate` | `ActionResult` | runs lau.harness.gate.promotion_gate | actions only; uses the holdout budget |
| POST `/approvals/{candidate_ref}/decision` `{decision: "approve"\|"reject", rationale}` | `ActionResult` | lau.promotion.promote.record_approval | actions only; requires a gate result |
| POST `/approvals/{candidate_ref}/promote` | `ActionResult` | lau.promotion.promote.promote | actions only |
| `/rollouts` | `RolloutsData` (`rollouts` with state shadow / serving / retired / rolled_back / superseded, events, approvals n of `required`, shadow `report`; `min_shadow_decisions`; `promotions`) | production.rollouts, ops.rollout_approvals, ops.decisions (shadow scores since each rollout started), production.promotions | |
| POST `/rollouts/{rollout_id}/decide` `{decision, note}` | `ActionResult` | lau.decision.rollout.record_decision (ops.rollout_approvals) | actions only; note of at least 10 characters; one decision per person |
| POST `/rollouts/{rollout_id}/serve` | `ActionResult` | lau.decision.rollout.serve: serving alias (promoter), decision model rebuild, endpoint update when it exists | actions only; needs the shadow minimum and the approvals, no rejection |
| POST `/rollouts/{rollout_id}/rollback` `{reason}` | `ActionResult` | lau.decision.rollout.rollback | actions only; one person; restores the previous serving model or the legacy policy |
| `/shadow` | `ShadowData` | ops.shadow_scores | available=false with reason if never run |
| `/readiness` | `ReadinessData` (items with evidence, sign-offs per role, state signed/open/declined; `ready`, `statement`) | config/readiness.yaml, ops.readiness_evidence (latest run), ops.signoffs | read-only: sign-offs are recorded at a terminal (`lau readiness sign`) |
| `/definitions/proposal` | `{proposal: DefinitionProposal \| null}` | config/default_definition.yaml, ops.definition_versions, ops.definition_approvals, pipeline stage catalog | null when the YAML is the active definition |
| POST `/definitions/{version}/approve` `{note}` | `ActionResult` | lau.definition.registry.record_approval (ops.definition_approvals) | actions only; only the YAML's exact hash; one approval per person |
| POST `/features/{name}/decision` `{decision: reject\|restore, reason}` | `ActionResult` | ops.feature_decisions | actions only; the harness fails candidates using a rejected feature |
| `/hypotheses`; POST `/hypotheses` `{text}`; POST `/hypotheses/{id}/unpin` | `PinnedHypothesis[]` / `ActionResult` | ops.pinned_hypotheses | pinned ones go to the planner every cycle |
| `/alerts` | `AlertsData` | ops.alerts, ops.alert_acks, ops.monitoring_runs | each alert carries a plain `title`, `current` (raised by the latest monitoring run) and `ack_at`/`ack_note`; open = current and not acknowledged (the status bar count) |
| POST `/alerts/{alert_id}/ack` `{note}` | `ActionResult` | writes ops.alert_acks (harness store) | actions only |
| `/cost` | `CostData` (with `billing` actuals from system.billing in mirror mode) | ops.cost_log, agent_trace (cost by agent), config project/budgets | billing_available=false unless system.billing readable; `by_agent` leaves out a running cycle (its cost is logged when it ends) so it matches the cost log |
| `/settings` | `SettingsData` | config/*.yaml, ops.config_versions, ops.access_checks | |
| `/search?q` | `SearchResult[]` | model_registry, cycles, feature_registry.features, data_catalog, reports, definition_versions | max 30 |
| POST `/ask` `{question}` | `AskResponse` | a read-only Claude agent (`lau.console.ask`, role `ask`, prompt `agents/prompts/ask.md`) with `describe_tables` and `sql_query` over the ui role; row-level `ops.shadow_scores` only through aggregates | 400 empty question; 503 without ANTHROPIC_API_KEY; 429 at the monthly hard stop; one question at a time; traced to ops.agent_trace and costed in ops.cost_log |

## New tables (written by the harness / pipeline identity; read by the console)

All timestamps UTC. `run_id` groups rows written together. Tables are partition-replaced per run or appended as noted.

### `ops.benchmark_results` (append per run)
`computed_at TIMESTAMP, run_id STRING, window_policy STRING, window_start STRING, window_end STRING,
performance_as_of STRING, data_version STRING, model_key STRING, model_name STRING, model_version STRING,
model_label STRING, model_kind STRING, trained_definition STRING, trained_data_version STRING,
selected_on_window BOOLEAN, benchmark_key STRING, benchmark_dpd INT, benchmark_version STRING, metric STRING,
value DOUBLE, ci_lo DOUBLE, ci_hi DOUBLE, n INT, n_defaults INT, is_best BOOLEAN, versus_key STRING`
- `metric` ∈ `auc`, `bad_rate_at_fixed_approval`, `auc_minus_reference`, `auc_minus_best_known`.
- `model_key` = `legacy_score` for the frozen reference, else `<model_name>/<version>`.
- `versus_key` set for the two diff metrics. `is_best` marks the best model per benchmark_key for `auc`
  (lowest for bad rate).

### `ops.definition_sensitivity` (append per run)
`computed_at, run_id, benchmark_key, benchmark_dpd INT, benchmark_version, period STRING (YYYY-Qn),
default_rate DOUBLE, n INT`

### `ops.vintage_curves` (append per run)
`computed_at, run_id, cohort STRING (YYYY-Hn), dpd_threshold INT, mob INT, cum_rate DOUBLE, n_loans INT`

### `ops.cashflow_cohorts` (append per run)
`computed_at, run_id, cohort STRING (YYYY-Qn), n INT, income_mean DOUBLE, income_cv_median DOUBLE,
expense_to_income_median DOUBLE, min_balance_median DOUBLE, nsf_rate DOUBLE, overdraft_share DOUBLE,
housing_on_time_mean DOUBLE`

### `ops.proxy_scan` (append per run)
`computed_at, run_id, definition_version, feature, protected_class, protected_group, proxy_auc DOUBLE, flagged BOOLEAN`
(aggregate only; no row-level protected attributes)

### `ops.improvement_ledger` (append per run)
`computed_at, run_id, active_definition, primary_benchmark, verdict_code, title, detail, best_known_key,
best_known_label, newest_challenger_key, newest_challenger_label, serving_key, lift_estimate DOUBLE, lift_lo DOUBLE,
lift_hi DOUBLE, guardrails_json STRING, denominator_json STRING`
- `verdict_code` ∈ `improved`, `no_change`, `not_best`, `regressed`, `insufficient_evidence` (rules: proposal
  "Proving the system improves").

### `ops.model_registry` (replaced on each sync)
`synced_at, model_name, version STRING, aliases STRING (comma-separated), tags_json STRING, definition_version,
lau_kind, lau_role, status STRING, run_id STRING, created_at TIMESTAMP, source_candidate_version STRING`
- `status` ∈ `serving`, `champion`, `challenger`, `candidate`, `baseline`, `retired`, `superseded`.

### `ops.evaluation_metrics` (replaced on each sync)
`eval_id, candidate_ref, definition_version, ts, metric STRING, value DOUBLE` (flattened from evaluations.result_json)

### `ops.config_versions` (append when a component's hash changes)
`recorded_at, component STRING, version_hash STRING, content_json STRING, git_sha STRING, recorded_by STRING, reason STRING`
- components: `thresholds`, `budgets`, `protected_classes`, `models`, `benchmarks`, `grants`, `prompt:<role>`, `code`.

### `ops.cycle_heartbeat` (append)
`ts, cycle_id, step STRING, agent STRING, state STRING, experiments_used INT, spent_usd DOUBLE`

### `ops.cycle_control` (append)
`ts, cycle_id, action STRING ('stop'), requested_by STRING, reason STRING, status STRING ('requested'|'honored')`

### `ops.access_checks` (append per check run)
`checked_at, role, object STRING (schema.table), expected STRING ('allow'|'deny'), observed STRING, ok BOOLEAN, detail STRING`

### `ops.alert_acks` (append)
`alert_id STRING, acked_at, acked_by, note`
- `alert_id` = first 12 hex of sha256 of `"{ts.isoformat()}|{kind}|{subject}"` from ops.alerts.
