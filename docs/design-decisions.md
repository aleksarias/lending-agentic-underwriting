# Design decisions

Each entry: decision, why, and what was verified vs. assumed.

## 1. Plain-Python orchestration, one SDK session per specialist
The orchestrator is Python; an LLM *planner* proposes a plan that Python validates and caps. Each specialist is a
separate `ClaudeSDKClient` session with its own system prompt, model, tool list, `max_turns`, `max_budget_usd` and
wall-clock timeout. SDK-native subagents were not used because caps, tool scoping and credential isolation are
easier to guarantee (and test) per session. Agents communicate only through artifacts: `experiments.reports`,
the feature registry, MLflow runs and `ops.evaluations` — never free chat.
*Verified:* `claude-agent-sdk` 0.2.162 source — `tools=[]` passes `--tools ""` (no built-ins); `env` is merged
over `os.environ` (hence explicit blanking); hooks require `ClaudeSDKClient`; allow-listed tools bypass
`can_use_tool`, so a `PreToolUse` hook gates every call.

## 2. Agent isolation
`tools=[]`, only `mcp__lau_<role>__*` allowed, built-ins also in `disallowed_tools`, `permission_mode="dontAsk"`,
`setting_sources=[]`, `skills=[]`, empty temp `cwd`, `DATABRICKS_CONFIG_FILE=/dev/null`, every `DATABRICKS_*`/
`LAU_*`/cloud env var blanked. Tools run in the orchestrator process as the **agent service principal**.
Unit-tested in `tests/unit/test_security.py::test_agent_options_are_locked_down`.

## 3. Three service principals, platform-enforced
`harness` (pipeline + evaluation; only holdout reader), `agent`, `promoter`. Grants are generated from one spec
(`governance/grants.py`) that is *also* enforced in-process by every Store. Proven against the live workspace by
`tests/integration/test_uc_isolation.py` (queries bypass the in-process ACL).
Agent-trained candidates are *registered* by the harness identity: UC model versions/aliases need model
ownership, and "agents propose, the harness records" matches the design principle.

## 4. Data access: SQL warehouse + UC volume staging (not Databricks Connect)
Reads use `databricks-sql-connector` (Arrow); DataFrame writes stage parquet to `/Volumes/<cat>/<schema>/landing`
and `CREATE TABLE AS / INSERT BY NAME ... FROM read_files(...)` (excluding the `_rescued_data` column
read_files adds). One compute type (a 2X-Small serverless warehouse), identical grants path for every identity,
and the same SQL runs against a local DuckDB lake for offline tests. Heavy compute (label building, training) is
pandas/LightGBM in the calling process at the default synthetic size; jobs run the same entry points on serverless.
*Verified:* Databricks Connect serverless requires Python 3.12 (docs table); project pinned to 3.12.

## 5. Definition versioning
`definition_version` = first 12 hex of SHA-256 over canonical JSON of the *semantic* fields plus a
`LABEL_LOGIC_VERSION`. `metadata` is excluded; exclusions are sorted/deduplicated; the custom SQL predicate is
normalized by sqlglot so formatting does not change the hash. Tests (a)–(e) in `tests/unit/test_definition.py`.

## 6. DAG with fingerprints
Fingerprint = hash(stage, code version, definition version if dependent, root input fingerprint, activation mode
for mode-sensitive stages, upstream fingerprints). Fresh iff a successful run with that fingerprint exists.
Re-activating an older, already-built definition re-points agent views and restarts the loop even though no stage
is stale (found by tests).

## 7. Label access contract
`labels_io` is the only reader: it requires the version, rejects inactive versions (except explicit
`compare`), verifies returned tags, and logs every read. Agents read the `labels_active` view: active version,
TRAIN split only. Holdout labels live in the `holdout` schema and are readable only via a gate-issued token.

## 8. Multiple testing
`margin(n) = base + k·sqrt(ln(1+n))` over validation tests for the definition version (defaults 0.002 and 0.003).
A pragmatic heuristic, not an exact correction: the expected maximum of m noisy AUC estimates grows ~sqrt(log m).
Resets per definition version because validation labels change. The holdout has its own budget (5 gate runs per
definition).

## 9. Leakage detection is multi-signal
Timestamp-after-decision, single-feature AUC, target-derived lineage, target-like names, and lineage availability.
The planted leak has single-feature AUC ≈0.75 (below the 0.85 threshold) and is caught only by the timestamp
check — keep all detectors. Categorical univariate AUC uses out-of-fold smoothed encoding (in-sample encoding made
a 900-level ZIP field look like a leak).

## 10. Reason codes without a SHAP dependency
LightGBM `pred_contrib` / XGBoost `pred_contribs` (TreeSHAP) and linear terms for LR, aggregated to input features.
Binding check: every simulated decline gets ≥1 principal reason from a permissible feature; "4 reasons" coverage
is informational (Reg B asks for the principal reasons, up to four).

## 11. Workspace adaptations (Phase 0)
- Default Storage: `CREATE CATALOG` works via SQL on serverless compute; the REST API requires a location.
- First workspace (`dbc-7505f6fd`) could not start any serverless compute (RESOURCE_EXHAUSTED); work moved to
  `dbc-67e8cd43` where a dedicated 2X-Small warehouse was created. Old workspace resources are listed in
  `.lau/old_workspace_dbc-7505f6fd_state.json` for cleanup.
- Pricing tier lacks IP access lists → network egress for agents is controlled in code (no web tools at all).

## Unsure / not verified
- Exact serverless SQL DBU rates for this account (config uses 4 DBU/h for 2X-Small, $0.70/DBU) — `lau cost`
  reports actuals from `system.billing.usage`.
- The bundle's scheduled `lau_improvement_cycle` job on serverless (needs secret scope `lau`; deployed paused).
