"""Column lists and dtypes of the evidence tables (docs/console/contract.md, "New tables").

`conform` is the single choke point every frame goes through before it is written, so a table always has exactly the
contract columns, in contract order, with portable dtypes (UTC-naive microsecond timestamps, nullable ints, NaN
as NULL) whatever a step happened to produce, including an empty frame.
"""

from __future__ import annotations

import pandas as pd

Kind = str  # "ts" | "str" | "float" | "int" | "bool"

TABLES: dict[str, list[tuple[str, Kind]]] = {
    "readiness_evidence": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("item_id", "str"),
        ("label", "str"),
        ("met", "bool"),
        ("detail", "str"),
    ],
    "policy_tradeoff": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("definition_version", "str"),
        ("model_label", "str"),
        ("window_start", "str"),
        ("window_end", "str"),
        ("n_applications", "int"),
        ("cutoff", "float"),
        ("approval_rate", "float"),
        ("expected_bad_rate", "float"),
        ("known_n", "int"),
        ("known_bad_rate", "float"),
        ("is_policy_approve", "bool"),
        ("is_policy_refer", "bool"),
    ],
    "production_evidence": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("definition_version", "str"),
        ("as_of_month", "str"),
        ("scope", "str"),
        ("key", "str"),
        ("model_version", "str"),
        ("n_booked", "int"),
        ("n_matured", "int"),
        ("n_defaults", "int"),
        ("realized_rate", "float"),
        ("predicted_pd", "float"),
        ("calibration_ratio", "float"),
        ("auc", "float"),
        ("brier", "float"),
    ],
    "decision_fairness": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("window_days", "int"),
        ("n_decisions", "int"),
        ("attribute", "str"),
        ("group", "str"),
        ("method", "str"),
        ("reference_group", "str"),
        ("n", "float"),
        ("approval_rate", "float"),
        ("decline_rate", "float"),
        ("air", "float"),
        ("below_threshold", "bool"),
    ],
    "serving_parity": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("window_days", "int"),
        ("feature", "str"),
        ("kind", "str"),
        ("in_serving_model", "bool"),
        ("psi", "float"),
        ("status", "str"),
        ("null_rate_train", "float"),
        ("null_rate_served", "float"),
        ("mean_train", "float"),
        ("mean_served", "float"),
        ("n_served", "int"),
    ],
    "benchmark_results": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("window_policy", "str"),
        ("window_start", "str"),
        ("window_end", "str"),
        ("performance_as_of", "str"),
        ("data_version", "str"),
        ("model_key", "str"),
        ("model_name", "str"),
        ("model_version", "str"),
        ("model_label", "str"),
        ("model_kind", "str"),
        ("trained_definition", "str"),
        ("trained_data_version", "str"),
        ("selected_on_window", "bool"),
        ("benchmark_key", "str"),
        ("benchmark_dpd", "int"),
        ("benchmark_version", "str"),
        ("metric", "str"),
        ("value", "float"),
        ("ci_lo", "float"),
        ("ci_hi", "float"),
        ("n", "int"),
        ("n_defaults", "int"),
        ("is_best", "bool"),
        ("versus_key", "str"),
    ],
    "definition_sensitivity": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("benchmark_key", "str"),
        ("benchmark_dpd", "int"),
        ("benchmark_version", "str"),
        ("period", "str"),
        ("default_rate", "float"),
        ("n", "int"),
    ],
    "vintage_curves": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("cohort", "str"),
        ("dpd_threshold", "int"),
        ("mob", "int"),
        ("cum_rate", "float"),
        ("n_loans", "int"),
    ],
    "cashflow_cohorts": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("cohort", "str"),
        ("n", "int"),
        ("income_mean", "float"),
        ("income_cv_median", "float"),
        ("expense_to_income_median", "float"),
        ("min_balance_median", "float"),
        ("nsf_rate", "float"),
        ("overdraft_share", "float"),
        ("housing_on_time_mean", "float"),
    ],
    "proxy_scan": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("definition_version", "str"),
        ("feature", "str"),
        ("protected_class", "str"),
        ("protected_group", "str"),
        ("proxy_auc", "float"),
        ("flagged", "bool"),
    ],
    "improvement_ledger": [
        ("computed_at", "ts"),
        ("run_id", "str"),
        ("active_definition", "str"),
        ("primary_benchmark", "str"),
        ("verdict_code", "str"),
        ("title", "str"),
        ("detail", "str"),
        ("best_known_key", "str"),
        ("best_known_label", "str"),
        ("newest_challenger_key", "str"),
        ("newest_challenger_label", "str"),
        ("serving_key", "str"),
        ("lift_estimate", "float"),
        ("lift_lo", "float"),
        ("lift_hi", "float"),
        ("guardrails_json", "str"),
        ("denominator_json", "str"),
    ],
    "model_registry": [
        ("synced_at", "ts"),
        ("model_name", "str"),
        ("version", "str"),
        ("aliases", "str"),
        ("tags_json", "str"),
        ("definition_version", "str"),
        ("lau_kind", "str"),
        ("lau_role", "str"),
        ("status", "str"),
        ("run_id", "str"),
        ("created_at", "ts"),
        ("source_candidate_version", "str"),
    ],
    "evaluation_metrics": [
        ("eval_id", "str"),
        ("candidate_ref", "str"),
        ("definition_version", "str"),
        ("ts", "ts"),
        ("metric", "str"),
        ("value", "float"),
    ],
}

# Replaced on every run; everything else is appended with a shared run_id.
OVERWRITE_TABLES = frozenset({"model_registry", "evaluation_metrics"})


def columns(table: str) -> list[str]:
    return [c for c, _ in TABLES[table]]


def _cast(s: pd.Series, kind: Kind) -> pd.Series:
    if kind == "ts":
        return pd.to_datetime(s, utc=True).dt.tz_localize(None).astype("datetime64[us]")
    if kind == "str":
        return s.astype("string")
    if kind == "float":
        return pd.to_numeric(s, errors="coerce").astype("float64")
    if kind == "int":
        return pd.to_numeric(s, errors="coerce").round().astype("Int64")
    if kind == "bool":
        return s.fillna(False).astype(bool)
    raise ValueError(f"unknown column kind {kind!r}")


def conform(table: str, df: pd.DataFrame) -> pd.DataFrame:
    """Exactly the contract columns, in order and typed; missing columns become NULL, extras are an error."""
    spec = TABLES[table]
    extra = set(df.columns) - {c for c, _ in spec}
    if extra:
        raise ValueError(f"ops.{table}: unexpected columns {sorted(extra)}")
    index = df.index if len(df) else pd.RangeIndex(0)
    out = {}
    for col, kind in spec:
        s = df[col] if col in df else pd.Series([None] * len(df), index=index, dtype="object")
        out[col] = _cast(s, kind)
    return pd.DataFrame(out).reset_index(drop=True)
