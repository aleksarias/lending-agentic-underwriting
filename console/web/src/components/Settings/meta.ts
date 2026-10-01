/**
 * Plain-language labels for the configuration the console shows. Wording follows the comments in config/*.yaml and the
 * code that reads each value. A key that is not listed here still renders, with its key turned into a label, so a new
 * setting never disappears from the page.
 */
import { roleLabel } from "../Agents/shared";

export type Fmt = "pct" | "usd" | "min" | "dbu" | "count" | "num" | "mono";

export interface Meta {
  label?: string;
  hint?: string;
  fmt?: Fmt;
  /** label for the row key of a wildcard entry (for example an agent role) */
  keyLabel?: (key: string) => string;
}

const META: Record<string, Meta> = {
  // ------------------------------------------------------------------------------------------ thresholds
  "thresholds.splits.train_frac": { label: "Training share", fmt: "pct", hint: "Share of eligible labelled loans used to train, cut by origination month." },
  "thresholds.splits.validation_frac": { label: "Validation share", fmt: "pct", hint: "Share used for validation. What remains after training and validation is the out-of-time holdout." },
  "thresholds.splits.early_stopping_tail_frac": { label: "Early-stopping share of training", fmt: "pct", hint: "Last share of the training months used to stop training early. Never validation data." },
  "thresholds.gate.base_auc_margin": { label: "Base AUC margin", fmt: "num", hint: "Validation AUC gain over the reference that a candidate needs, before the multiple-testing penalty." },
  "thresholds.gate.mt_penalty_k": { label: "Multiple-testing penalty (k)", fmt: "num", hint: "The required margin grows by k times the square root of ln(1 + tests run under the definition)." },
  "thresholds.gate.holdout_auc_tolerance": { label: "Holdout AUC tolerance", fmt: "num", hint: "The candidate's holdout AUC must be at least the reference's holdout AUC minus this." },
  "thresholds.gate.max_ece": { label: "Maximum calibration error (ECE)", fmt: "num", hint: "Expected calibration error on validation." },
  "thresholds.gate.max_slice_auc_drop": { label: "Maximum time-slice AUC drop", fmt: "num", hint: "How far the worst time slice may fall below the overall AUC." },
  "thresholds.gate.max_score_psi": { label: "Maximum score PSI", fmt: "num", hint: "Score drift between training and validation." },
  "thresholds.gate.min_segment_auc": { label: "Minimum segment AUC", fmt: "num", hint: "Lowest AUC allowed in any segment." },
  "thresholds.leakage.single_feature_auc_max": { label: "Maximum single-feature AUC", fmt: "num", hint: "A feature that alone ranks defaults better than this is treated as leakage." },
  "thresholds.leakage.post_decision_share_max": { label: "Maximum share recorded after the decision", fmt: "pct", hint: "Share of rows whose value carries a timestamp later than the decision." },
  "thresholds.leakage.target_like_name_patterns": { label: "Names treated as target-like", hint: "A column whose name contains one of these is flagged as possible leakage." },
  "thresholds.fairness.approval_rate": { label: "Approval rate for adverse-impact tests", fmt: "pct", hint: "The lowest-risk share of applicants approved when adverse impact is calculated." },
  "thresholds.fairness.min_air": { label: "Minimum adverse impact ratio", fmt: "num", hint: "Four-fifths rule. Below it the gate fails." },
  "thresholds.fairness.proxy_auc_flag": { label: "Proxy AUC flag", fmt: "num", hint: "A feature that alone predicts protected-group membership better than this is flagged as a proxy." },
  "thresholds.monitoring.psi_warn": { label: "PSI warning level", fmt: "num", hint: "Drift at or above this is a warning." },
  "thresholds.monitoring.psi_alert": { label: "PSI alert level", fmt: "num", hint: "Drift at or above this raises an alert." },
  "thresholds.monitoring.default_rate_rel_tol": { label: "Default-rate tolerance", fmt: "pct", hint: "How far the observed default rate may differ from the expected one, relative, before an alert." },
  "thresholds.monitoring.early_indicator_dpd": { label: "Early indicator: days past due", fmt: "count", hint: "Delinquency level read as an early warning." },
  "thresholds.monitoring.early_indicator_mob": { label: "Early indicator: month on book", fmt: "count", hint: "Month on book at which the early indicator is read." },
  "thresholds.reason_codes.top_n": { label: "Reasons per decline", fmt: "count", hint: "Top reasons reported for each declined application." },
  // -------------------------------------------------------------------------------------------- budgets
  "budgets.cycle.max_databricks_dbu": { label: "Databricks cap", fmt: "dbu", hint: "Estimated warehouse use one cycle may plan." },
  "budgets.cycle.max_anthropic_usd": { label: "Agent spend cap", fmt: "usd", hint: "Anthropic spend one cycle may reach." },
  "budgets.cycle.max_wall_clock_min": { label: "Wall-clock cap", fmt: "min", hint: "The cycle ends when it reaches this." },
  "budgets.cycle.max_experiments": { label: "Validation tests cap", fmt: "count", hint: "Candidate evaluations against validation in one cycle." },
  "budgets.cycle.max_critique_rounds": { label: "Red-team revision rounds", fmt: "count", hint: "How often a failed red-team review sends the candidate back to the modeling agent." },
  "budgets.cycle.max_features_proposed": { label: "Features proposed cap", fmt: "count", hint: "Engineered features the feature agent may propose in one cycle." },
  "budgets.monthly.hard_stop_usd": { label: "Monthly hard stop", fmt: "usd", hint: "Databricks (estimated and actual) plus Anthropic, per calendar month. A cycle that would pass it is refused." },
  "budgets.agents.*.max_turns": { label: "Turn cap", fmt: "count" },
  "budgets.agents.*.max_budget_usd": { label: "Budget cap", fmt: "usd" },
  "budgets.agents.*.timeout_min": { label: "Time limit", fmt: "min" },
  "budgets.agents.*": { keyLabel: roleLabel },
  "budgets.holdout.max_gate_evaluations_per_definition": { label: "Holdout gate runs per definition", fmt: "count", hint: "The holdout is a scarce resource too: each gate run reads it." },
  // ---------------------------------------------------------------------------------------------- models
  "models.agents.*": { fmt: "mono", keyLabel: roleLabel },
  "models.estimate_usd_per_run.*": { fmt: "usd", keyLabel: roleLabel },
  // ------------------------------------------------------------------------------------------ protected
  "protected_classes.protected_classes.*": { keyLabel: (k) => humanize(k) },
  "protected_classes.protected_classes.*.column": { label: "Data column", fmt: "mono" },
  "protected_classes.protected_classes.*.reference_group": { label: "Reference group" },
  "protected_classes.protected_classes.*.protected_groups": { label: "Protected groups" },
  "protected_classes.prohibited_features": { label: "Prohibited features", hint: "A model may never use these columns." },
};

export const GROUP_TITLES: Record<string, string> = {
  "thresholds.splits": "Data splits",
  "thresholds.gate": "Promotion gate and validation checks",
  "thresholds.leakage": "Leakage screen",
  "thresholds.fairness": "Fairness",
  "thresholds.monitoring": "Monitoring",
  "thresholds.reason_codes": "Reason codes",
  "budgets.cycle": "Per improvement cycle",
  "budgets.monthly": "Per month",
  "budgets.agents": "Per agent run",
  "budgets.holdout": "Holdout",
  "models.agents": "Claude model for each agent role",
  "models.estimate_usd_per_run": "Planning estimate per agent run (US dollars)",
  "protected_classes.protected_classes": "Protected classes",
  "protected_classes.__flat": "Prohibited features",
};

const EXPLAIN_GROUP: Record<string, string> = {
  "models.estimate_usd_per_run": "Rough priors used only for the estimate shown before a cycle starts. Actual cost comes from the API, per run.",
};
export const groupNote = (path: string) => EXPLAIN_GROUP[path];

/** Exact path first, then the same path with one segment (a row key such as an agent role) replaced by "*". */
export function metaFor(path: string[]): Meta | undefined {
  const exact = META[path.join(".")];
  if (exact) return exact;
  for (let i = path.length - 1; i >= 1; i--) {
    const wild = [...path.slice(0, i), "*", ...path.slice(i + 1)].join(".");
    if (META[wild]) return META[wild];
  }
  return undefined;
}

/** snake_case key as a sentence-case label. */
export function humanize(key: string): string {
  const t = key.replace(/_/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}
