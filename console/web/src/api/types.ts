/**
 * Underwriting Console API contract — THE source of truth for request/response shapes.
 *
 * The FastAPI backend (src/lau/console/routers/*) returns exactly these shapes; every page consumes them through
 * the hooks in ./hooks.ts. Conventions:
 *  - Timestamps are ISO-8601 strings in UTC. Months are "YYYY-MM", quarters "YYYY-Qn", half-years "YYYY-Hn".
 *  - Rates/probabilities are fractions (0.123 = 12.3%). AUC values are 0..1.
 *  - Anything not built yet (decision API, live loan feed, rollout stages, notifications) returns an
 *    `Unavailable` object instead of failing, so pages can render a designed empty state.
 *  - `definition_version` is the 12-hex content hash; `short` is its first 8 characters.
 *  - Missing numbers are `null`, never NaN.
 */

export type ISODate = string;
export type Tone = "good" | "warn" | "crit" | "neutral" | "accent";

export interface Unavailable {
  available: false;
  reason: string;
  requires: string[];
}
export const isUnavailable = (x: unknown): x is Unavailable =>
  !!x && typeof x === "object" && (x as { available?: unknown }).available === false;

export interface Interval {
  estimate: number;
  lo: number;
  hi: number;
  n?: number | null;
}

export interface DefinitionRef {
  version: string;
  short: string;
  name: string;
  /** e.g. "60 DPD ever / 12 months" */
  summary: string;
  dpd: number;
  timing: "ever" | "end_of_window";
  window_months: number;
}

export type ModelKind =
  | "reference"
  | "baseline"
  | "challenger"
  | "champion"
  | "retrained_champion_arch"
  | "candidate"
  | "unknown";

export interface ModelRef {
  /** Stable key: "legacy_score" or "<registered model name>/<version>" */
  key: string;
  name: string;
  version: string;
  /** Short human label, e.g. "v11" or "Legacy policy score" */
  label: string;
  kind: ModelKind;
  definition_version: string | null;
}

export interface Tile {
  key: string;
  label: string;
  value: string;
  sub?: string | null;
  tone?: Tone | null;
  href?: string | null;
}

export interface BadgeSpec {
  label: string;
  tone: Tone;
}

// ------------------------------------------------------------------------------------------------ status / overview
export type ActivityState = "idle" | "cycle_running" | "pipeline_rebuilding";
export type VerdictCode = "improved" | "no_change" | "not_best" | "regressed" | "insufficient_evidence";

export interface StatusSummary {
  generated_at: ISODate;
  environment: "dev" | "prod";
  data_mode: "synthetic" | "real";
  backend: "databricks" | "local";
  active_definition: DefinitionRef | null;
  yaml_definition_version: string | null;
  yaml_matches_active: boolean;
  serving: ModelRef | null;
  serving_superseded: boolean;
  /** stale = harness facts (evaluations, definition changes, data loads, promotions) exist that the verdict predates */
  verdict: { code: VerdictCode; title: string; stale?: boolean } | null;
  activity: { state: ActivityState; cycle_id?: string | null; step?: string | null; since?: ISODate | null };
  budget: { month_to_date_usd: number; hard_stop_usd: number };
  decisions_waiting: number;
  alerts_open: { high: number; medium: number };
  api: { live: boolean; p99_ms?: number | null; fallback_rate?: number | null };
  feed: { live: boolean; last_received_at?: ISODate | null; quality_failures?: number | null };
  actions_enabled: boolean;
  user: string;
}

export type EventType =
  | "definition_activated"
  | "data_loaded"
  | "stage_built"
  | "stage_failed"
  | "cycle_started"
  | "cycle_finished"
  | "evaluation"
  | "gate"
  | "approval"
  | "promotion"
  | "rollback"
  | "alert"
  | "budget_stop"
  | "config_changed"
  | "report"
  | "benchmark";

export interface EventItem {
  id: string;
  ts: ISODate;
  type: EventType;
  title: string;
  detail?: string | null;
  definition_version?: string | null;
  actor?: string | null;
  tone: Tone;
  href?: string | null;
}

export interface WaitingItem {
  id: string;
  kind: "promotion" | "definition_change" | "policy_change" | "rollout" | "config_change";
  title: string;
  created_at: ISODate;
  badges: BadgeSpec[];
  href: string;
}

export interface StageFreshness {
  stage: string;
  status: "fresh" | "stale" | "failed" | "never";
  last_run_at: ISODate | null;
  duration_s: number | null;
  definition_version: string | null;
  reason?: string | null;
}

export interface OverviewData {
  status_sentence: string;
  tiles: Tile[];
  waiting: WaitingItem[];
  recent_events: EventItem[];
  pipeline: StageFreshness[];
}

// ----------------------------------------------------------------------------------------------------- activity
export interface AgentLane {
  role: string;
  state: "pending" | "running" | "done" | "error";
  turns: number;
  max_turns: number;
  cost_usd: number;
  max_cost_usd: number;
  started_at?: ISODate | null;
  finished_at?: ISODate | null;
}

export interface Gauge {
  key: string;
  label: string;
  used: number;
  cap: number;
  unit: string;
}

export interface TraceEntry {
  id: string;
  ts: ISODate;
  cycle_id: string;
  agent: string;
  action: string;
  status: string;
  state_changing: boolean;
  /** One line: tool + key inputs + outcome */
  summary: string;
  /** "proposed" = agent claim, "measured" = harness/tool result, "system" = orchestration */
  kind: "proposed" | "measured" | "system";
  cost_usd: number;
  inputs?: string | null;
  outputs?: string | null;
}

export interface CycleSummary {
  cycle_id: string;
  definition_version: string;
  reason: string;
  status: string;
  started_at: ISODate;
  anthropic_usd: number | null;
  challenger: string | null;
  challenger_passed_validation: boolean | null;
  redteam_verdict: string | null;
  compliance_verdict: string | null;
  experiments_used: number | null;
  stop_reason: string | null;
}

export interface CycleLive {
  cycle_id: string;
  definition_version: string;
  started_at: ISODate;
  state: "running" | "stopping";
  current_step: string | null;
  heartbeat_at: ISODate | null;
  lanes: AgentLane[];
  gauges: Gauge[];
  trace: TraceEntry[];
}

export interface ActivityData {
  cycle: CycleLive | null;
  last_cycle: CycleSummary | null;
  pipeline: StageFreshness[];
}

export interface ReportMeta {
  report_id: string;
  cycle_id: string;
  author: string;
  kind: string;
  title: string;
  verdict: string | null;
  candidate_ref: string | null;
  created_at: ISODate;
  definition_version: string;
}

export interface Report extends ReportMeta {
  body: string;
}

export interface CycleDetail extends CycleSummary {
  plan: Record<string, unknown> | null;
  steps: { role: string; subtype: string; turns: number; cost_usd: number; tool_calls: number; duration_s: number }[];
  reports: ReportMeta[];
  trace: TraceEntry[];
  report_markdown: string | null;
}

// ----------------------------------------------------------------------------------------------------- progress
export interface Verdict {
  code: VerdictCode;
  title: string;
  detail: string;
  computed_at: ISODate | null;
  primary_benchmark: string;
  best_known: ModelRef | null;
  newest_challenger: ModelRef | null;
  serving: ModelRef | null;
  lift_vs_reference: Interval | null;
  /** Set when newer harness facts exist than this evidence run (the verdict may be out of date), else null */
  stale_reason?: string | null;
}

export interface BenchmarkDef {
  key: string;
  label: string;
  dpd: number;
  version: string;
  n_defaults: number;
}

export interface BenchmarkCell {
  auc: number;
  ci_lo?: number | null;
  ci_hi?: number | null;
}

export interface BenchmarkRow {
  model: ModelRef;
  /** e.g. "60 DPD, data v2" or "—" for the reference */
  trained_under: string;
  data_version: string | null;
  metrics: Record<string, BenchmarkCell>; // keyed by BenchmarkDef.key
  bad_rate_at_fixed_approval: number | null;
  is_best: Record<string, boolean>;
  /** True when this model was selected/evaluated on the benchmark window (optimistic) */
  selected_on_window: boolean;
}

export interface BenchmarkMatrix {
  computed_at: ISODate;
  window: { start: string; end: string; n_loans: number; policy: string };
  fixed_approval_rate: number;
  definitions: BenchmarkDef[];
  primary_definition: string;
  rows: BenchmarkRow[];
}

export interface DiffRow {
  model: ModelRef;
  versus: ModelRef;
  definition_key: string;
  diff: Interval;
}

export interface LineagePoint {
  period: string;
  model: ModelRef;
  lift_vs_reference: Interval;
  definition_version: string;
  event?: "promotion" | "rollback" | "definition_change" | null;
}

export interface GuardrailRow {
  key: string;
  label: string;
  value: number | null;
  threshold: number | null;
  direction: "max" | "min";
  status: "ok" | "watch" | "breach" | "unknown";
  history: { ts: ISODate; value: number }[];
}

export interface ProcessHealth {
  cycles_total: number;
  cycles_completed: number;
  candidates_evaluated: number;
  candidates_passed: number;
  anthropic_usd_total: number;
  cost_per_passed_candidate: number | null;
  months: { month: string; cycles: number; passed: number; cost_usd: number }[];
}

export interface Denominator {
  definition_version: string;
  tests_since_reset: number;
  tests_total: number;
  next_margin: number;
  holdout_used: number;
  holdout_budget: number;
  candidates: { ref: string; auc: number | null; passed: boolean | null; ts: ISODate }[];
}

export interface ProductionEvidence {
  available: true;
  vintages: {
    cohort: string;
    model: ModelRef;
    predicted: number;
    realized_early: number | null;
    realized_final: number | null;
    n: number;
  }[];
}

export interface ProgressData {
  verdict: Verdict | null;
  benchmark: BenchmarkMatrix | null;
  reference_diffs: DiffRow[];
  best_known_diffs: DiffRow[];
  lineage: LineagePoint[];
  guardrails: GuardrailRow[];
  process_health: ProcessHealth;
  denominator: Denominator | null;
  production: Unavailable | ProductionEvidence;
}

// -------------------------------------------------------------------------------------------------- definitions
export interface LabelStats {
  n_loans: number;
  n_eligible: number;
  n_default: number;
  default_rate: number;
  exclusions: Record<string, number>;
  triggers: Record<string, number>;
}

export interface SplitMeta {
  train: [string, string];
  validation: [string, string];
  oot: [string, string];
  n: Record<string, number>;
  default_rate: Record<string, number>;
}

export interface FieldDiff {
  field: string;
  before: unknown;
  after: unknown;
}

export interface DefinitionVersion {
  version: string;
  short: string;
  name: string;
  description: string;
  plain_language: string;
  fields: Record<string, unknown>;
  created_at: ISODate | null;
  active_from: ISODate | null;
  active_to: ISODate | null;
  is_active: boolean;
  activated_by: string | null;
  approval_id: string | null;
  label_stats: LabelStats | null;
  split: SplitMeta | null;
  diff_vs_previous: FieldDiff[];
}

export interface SensitivityData {
  computed_at: ISODate | null;
  series: { definition_key: string; label: string; dpd: number; points: { period: string; default_rate: number; n: number }[] }[];
}

export interface PipelineData {
  definition_version: string | null;
  stages: StageFreshness[];
  runs: {
    stage: string;
    definition_version: string;
    status: string;
    started_at: ISODate;
    finished_at: ISODate;
    duration_s: number;
  }[];
}

// ------------------------------------------------------------------------------------------------------ history
export interface EventsPage {
  events: EventItem[];
  next_before: ISODate | null;
}

export interface ChangeSet {
  from: ISODate;
  to: ISODate;
  components: {
    component: string;
    before: string | null;
    after: string | null;
    changed: boolean;
    detail?: string | null;
    href?: string | null;
  }[];
  events_between: EventItem[];
}

export interface LineageGraph {
  nodes: {
    id: string;
    type: "data" | "definition" | "labels" | "features" | "run" | "model" | "evaluation" | "gate" | "approval" | "promotion";
    label: string;
    detail?: string | null;
    href?: string | null;
  }[];
  edges: { from: string; to: string }[];
}

// ----------------------------------------------------------------------------------------------------- upcoming
export interface JobInfo {
  name: string;
  paused: boolean;
  schedule: string | null;
  next_run_at: ISODate | null;
  last_result: string | null;
  last_run_at: ISODate | null;
}

export interface QueueItem {
  requested_at: ISODate;
  definition_version: string;
  reason: string;
  status: string;
}

export interface UpcomingData {
  jobs: JobInfo[] | Unavailable;
  queue: QueueItem[];
  next_plan: Record<string, unknown> | null;
  waiting: WaitingItem[];
  forecast: {
    month_end_usd: number | null;
    tests_since_reset: number;
    next_margin: number;
    holdout_remaining: number;
    maturation: { definition_version: string; months_until_next_window: number | null; note: string } | null;
  };
  backlog: { hypothesis: string; source: string }[];
}

// ------------------------------------------------------------------------------------------------------- models
export type ModelStatus =
  | "serving"
  | "champion"
  | "challenger"
  | "candidate"
  | "baseline"
  | "retired"
  | "superseded";

export interface ModelVersion {
  model: ModelRef;
  status: ModelStatus;
  aliases: string[];
  created_at: ISODate | null;
  model_type: string | null;
  n_features: number | null;
  val_auc: number | null;
  passed_validation: boolean | null;
  author: string | null;
  cycle_id: string | null;
}

export interface EvaluationSummary {
  eval_id: string;
  candidate_ref: string;
  definition_version: string;
  ts: ISODate;
  val_auc: number;
  reference_auc: number | null;
  required_margin: number;
  n_tests: number;
  passed_validation: boolean;
}

export interface GateSummary {
  gate_id: string;
  candidate_ref: string;
  ts: ISODate;
  passed: boolean;
  holdout_auc: number;
  reference_holdout_auc: number;
  checks: Record<string, boolean>;
}

export interface ApprovalRecord {
  approval_id: string;
  kind: "promotion" | "definition";
  ref: string;
  definition_version: string;
  decision: string;
  approver: string;
  rationale: string;
  ts: ISODate;
}

export interface ModelCard {
  model: ModelRef;
  status: ModelStatus;
  aliases: string[];
  tags: Record<string, string>;
  description: { model_type: string; params: Record<string, unknown>; features: string[]; engineered: string[] } | null;
  engineered: { name: string; expression: string; rationale: string }[];
  evaluations: EvaluationSummary[];
  gate: GateSummary | null;
  reports: ReportMeta[];
  approvals: ApprovalRecord[];
  benchmark: BenchmarkRow | null;
  feature_importance: { feature: string; share: number }[];
}

export interface FairnessDetail {
  cutoff_pd: number | null;
  min_air: number | null;
  classes: Record<
    string,
    { reference_group: string; approval_rates: Record<string, number>; air: Record<string, number>; min_air: number | null }
  >;
}

export interface EvaluationDetail extends EvaluationSummary {
  validation: Record<string, number | null>;
  lift: { decile: number; n: number; default_rate: number; mean_pd: number; lift: number; cum_capture: number }[];
  calibration: { bin: number; n: number; predicted: number; observed: number }[];
  time_slices: Record<string, number>;
  segments: Record<string, number>;
  thin_file_auc: number | null;
  score_psi: number | null;
  checks: Record<string, boolean>;
  leakage: { column: string; risk: string; reasons: string[] }[];
  fairness: FairnessDetail;
  proxies_flagged: string[];
  reason_codes: {
    quality: Record<string, unknown>;
    sample: { application_id: string; rank: number; feature: string; reason_text: string }[];
  };
  feature_importance: { feature: string; share: number }[];
  model: { model_type: string; features: string[]; engineered: string[] };
  reference: { kind: string; auc: number | null; model_version?: string | null };
}

export interface PerformanceData {
  definition_version: string;
  definitions: DefinitionRef[];
  evaluations: EvaluationSummary[];
  ledger: {
    n_tests: number;
    required_margin: number;
    reference_auc: number | null;
    candidate_ref: string;
    val_auc: number;
    passed: boolean;
    ts: ISODate;
  }[];
  holdout: { used: number; budget: number; gates: GateSummary[] };
}

// ----------------------------------------------------------------------------------------------------- fairness
export interface FairnessData {
  definition_version: string;
  threshold_air: number;
  approval_rate: number;
  candidates: { candidate_ref: string; eval_id: string; ts: ISODate; min_air: number | null; classes: FairnessDetail["classes"] }[];
  proxy_heatmap: {
    feature: string;
    protected_class: string;
    protected_group: string | null;
    proxy_auc: number;
    flagged: boolean;
  }[];
  proxy_threshold: number;
  prohibited_features: string[];
  findings: ReportMeta[];
}

// ------------------------------------------------------------------------------------------------ feed / vintage
export interface VintageData {
  computed_at: ISODate | null;
  dpd_thresholds: number[];
  cohorts: { cohort: string; n: number; curves: Record<string, number[]> }[]; // curves keyed by dpd, index = MOB-1
}

export interface FeedData {
  live: boolean;
  reason: string;
  requires: string[];
  performance: {
    data_version: string | null;
    as_of_month: string | null;
    loaded_at: ISODate | null;
    n_applications: number | null;
  };
  vintage: VintageData;
  maturation: { definition_version: string; short: string; n_eligible: number; n_default: number; default_rate: number; excluded: Record<string, number> }[];
}

// ---------------------------------------------------------------------------------------------- catalog / data
export interface CatalogVariable {
  variable: string;
  dtype: string;
  description: string;
  source_system: string;
  availability: string;
  missing_rate: number | null;
  cardinality: number | null;
  univariate_auc_train: number | null;
  drift_psi: number | null;
  leakage_risk: "high" | "medium" | "low";
  leakage_reasons: string;
  proxy_risk: "high" | "low";
  proxy_auc: number | null;
  proxy_class: string | null;
  prohibited: boolean;
  mean: number | null;
  p01: number | null;
  p50: number | null;
  p99: number | null;
  top_values: Record<string, number> | null;
}

export interface CatalogData {
  definition_version: string;
  definitions: DefinitionRef[];
  variables: CatalogVariable[];
}

export interface CashflowCohorts {
  computed_at: ISODate | null;
  cohorts: {
    cohort: string;
    n: number;
    income_mean: number | null;
    income_cv_median: number | null;
    expense_to_income_median: number | null;
    min_balance_median: number | null;
    nsf_rate: number | null;
    overdraft_share: number | null;
    housing_on_time_mean: number | null;
  }[];
}

// ----------------------------------------------------------------------------------------------------- features
export interface FeatureRow {
  name: string;
  expression: string;
  rationale: string;
  hypothesis: string;
  author: string;
  cycle_id: string;
  created_at: ISODate;
  created_under_definition: string;
  status: string;
  performance: Record<string, { auc: number | null; missing_rate: number | null; leakage_risk: string | null; proxy_risk: string | null }>;
  used_in: string[];
}

// ------------------------------------------------------------------------------------------------------- agents
export interface AgentInfo {
  role: string;
  model: string;
  caps: { max_turns: number; max_budget_usd: number; timeout_min: number };
  prompt_hash: string;
  tools: string[];
  runs: number;
  total_cost_usd: number;
  avg_turns: number | null;
  tool_error_rate: number | null;
}

export interface Lesson {
  id: string;
  definition_version: string;
  scope: string;
  status: string;
  text: string;
}

export interface LessonsData {
  active_definition: string | null;
  lessons: Lesson[];
}

// ---------------------------------------------------------------------------------------------------- approvals
export interface ApprovalsData {
  pending: WaitingItem[];
  history: ApprovalRecord[];
  actions_enabled: boolean;
}

export interface EvidencePacket {
  candidate_ref: string;
  model: ModelRef;
  definition_version: string;
  evaluation: EvaluationSummary | null;
  checks: Record<string, boolean>;
  benchmark: { row: BenchmarkRow | null; best_known: ModelRef | null; beats_best_known: boolean | null };
  gate: GateSummary | null;
  reports: ReportMeta[];
  fairness_min_air: number | null;
  cost_usd: number | null;
  can_run_gate: boolean;
  can_decide: boolean;
  can_promote: boolean;
  blockers: string[];
}

export interface ActionResult {
  ok: boolean;
  message: string;
  ref?: string | null;
}

// ------------------------------------------------------------------------------- rollouts / shadow / alerts / api
export interface Promotion {
  promotion_id: string;
  ts: ISODate;
  definition_version: string;
  production_model_version: string;
  candidate_model_version: string;
  previous_champion_version: string | null;
  serving: boolean;
  approval_id: string;
}

export interface RolloutsData {
  live: Unavailable;
  promotions: Promotion[];
}

export interface ShadowData {
  available: boolean;
  reason: string | null;
  runs: { scored_at: ISODate; definition_version: string; role: string; model_version: string; n: number; mean_pd: number }[];
  distributions: { role: string; bins: { edge: number; share: number }[] }[];
  agreement_at_policy: number | null;
}

export interface AlertItem {
  id: string;
  ts: ISODate;
  kind: string;
  subject: string;
  value: number;
  severity: "high" | "medium" | "low";
  definition_version: string;
  acknowledged: boolean;
  ack_by: string | null;
}

export interface AlertsData {
  available: boolean;
  reason: string | null;
  alerts: AlertItem[];
  monitoring_runs: { ts: ISODate; definition_version: string; score_psi: number | null; max_feature_psi: number | null; alerts: number }[];
}

export interface DecisionsData {
  live: Unavailable;
  preview: { endpoint: string; example_response: Record<string, unknown>; policy_version: string | null };
}

// --------------------------------------------------------------------------------------------------------- cost
export interface CostData {
  month_to_date_usd: number;
  hard_stop_usd: number;
  cycle_caps: { anthropic_usd: number; dbu: number };
  by_day: { day: string; anthropic: number; databricks: number }[];
  by_cycle: { cycle_id: string; anthropic: number; databricks: number }[];
  by_agent: { agent: string; cost_usd: number; runs: number }[];
  pricing: { usd_per_dbu: number; dbu_per_hour: number; warehouse_size: string };
  billing_available: boolean;
}

// ------------------------------------------------------------------------------------------------------ settings
export interface SettingsData {
  thresholds: Record<string, unknown>;
  budgets: Record<string, unknown>;
  models: Record<string, unknown>;
  benchmarks: { key: string; dpd: number; version: string }[];
  protected_classes: Record<string, unknown>;
  config_versions: { component: string; version: string; recorded_at: ISODate; git_sha: string | null }[];
  access_checks: { role: string; object: string; expected: "allow" | "deny"; observed: string; ok: boolean; checked_at: ISODate }[];
  notifications: Unavailable;
}

// ---------------------------------------------------------------------------------------------- search / ask
export interface SearchResult {
  type: "model" | "cycle" | "feature" | "variable" | "report" | "definition";
  id: string;
  title: string;
  subtitle?: string | null;
  href: string;
}

export interface AskResponse {
  answer: string;
  queries: { sql: string; rows: number }[];
  cost_usd: number;
  model: string;
}
