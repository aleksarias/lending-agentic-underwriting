"""Harness evaluations, promotion-gate results and approvals as the console shows them.

`ops.evaluations.result_json` (see lau.harness.evaluate) holds the full evidence; list views read only the scalar
columns so a page never drags megabytes of JSON out of the warehouse.
"""

from __future__ import annotations

import pandas as pd

from lau.console import deps
from lau.console.services import config
from lau.console.util import boolean, col, integer, iso, loads, num, read_table, sql_str, text, ttl_cache

_EVAL_COLS = [
    "eval_id",
    "candidate_ref",
    "definition_version",
    "ts",
    "passed_validation",
    "val_auc",
    "reference_auc",
    "required_margin",
    "n_tests",
]
_GATE_COLS = ["gate_id", "candidate_ref", "definition_version", "ts", "passed", "holdout_auc", "reference_holdout_auc"]


@ttl_cache(30)
def evaluations() -> pd.DataFrame:
    """Scalar columns of every evaluation, newest first."""
    df = read_table(deps.ui_store(), "ops", "evaluations", columns=_EVAL_COLS, ts=["ts"])
    return df.sort_values("ts", ascending=False).reset_index(drop=True) if len(df) else df


def latest_per_ref(df: pd.DataFrame) -> pd.DataFrame:
    """The newest evaluation of each candidate ref."""
    if df.empty:
        return df
    return df.sort_values("ts", ascending=False).drop_duplicates("candidate_ref", keep="first").reset_index(drop=True)


def summary_from_row(r: dict) -> dict:
    """EvaluationSummary from an evaluations row."""
    return {
        "eval_id": str(r["eval_id"]),
        "candidate_ref": str(r["candidate_ref"]),
        "definition_version": str(r["definition_version"]),
        "ts": iso(r["ts"]),
        "val_auc": num(r.get("val_auc")) or 0.0,
        "reference_auc": num(r.get("reference_auc")),
        "required_margin": num(r.get("required_margin")) or 0.0,
        "n_tests": integer(r.get("n_tests")) or 0,
        "passed_validation": bool(boolean(r.get("passed_validation"))),
    }


def summaries(df: pd.DataFrame) -> list[dict]:
    return [summary_from_row(r) for r in df.to_dict("records")] if len(df) else []


@ttl_cache(60)
def feature_counts() -> dict[str, int]:
    """{eval_id: number of model features} for the newest evaluation of each ref (read from result_json)."""
    df = latest_per_ref(evaluations())
    if df.empty:
        return {}
    ids = ", ".join(sql_str(x) for x in df["eval_id"])
    rows = read_table(
        deps.ui_store(), "ops", "evaluations", columns=["eval_id", "result_json"], where=f"eval_id IN ({ids})"
    )
    out = {}
    for r in rows.to_dict("records") if len(rows) else []:
        feats = ((loads(r.get("result_json"), {}) or {}).get("model") or {}).get("features")
        if isinstance(feats, list):
            out[str(r["eval_id"])] = len(feats)
    return out


def latest_evaluation_row(candidate_ref: str) -> dict | None:
    df = evaluations()
    if df.empty:
        return None
    hit = df[df["candidate_ref"] == candidate_ref]
    return None if hit.empty else hit.iloc[0].to_dict()


def result_json(eval_id: str) -> dict:
    """The parsed result_json of one evaluation ({} when missing)."""
    df = read_table(
        deps.ui_store(), "ops", "evaluations", columns=["result_json"], where=f"eval_id = {sql_str(eval_id)}", limit=1
    )
    return (loads(df["result_json"].iloc[0], {}) or {}) if len(df) else {}


def latest_result(candidate_ref: str) -> tuple[dict | None, dict]:
    """(evaluation row, parsed result_json) for the newest evaluation of a ref."""
    row = latest_evaluation_row(candidate_ref)
    return (row, result_json(row["eval_id"])) if row else (None, {})


def evaluation_detail(eval_id: str) -> dict | None:
    df = read_table(deps.ui_store(), "ops", "evaluations", where=f"eval_id = {sql_str(eval_id)}", limit=1, ts=["ts"])
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    res = loads(row.get("result_json"), {}) or {}
    fair = res.get("fairness") or {}
    classes = {
        str(name): {
            "reference_group": str(c.get("reference_group", "")),
            "approval_rates": {str(k): num(v) for k, v in (c.get("approval_rates") or {}).items()},
            "air": {str(k): num(v) for k, v in (c.get("air") or {}).items()},
            "min_air": num(c.get("min_air")),
            "mean_pd": {str(k): num(v) for k, v in (c.get("mean_pd") or {}).items()},
        }
        for name, c in (fair.get("classes") or {}).items()
    }
    model = res.get("model") or {}
    reference = res.get("reference") or {}
    ref_out = {"kind": str(reference.get("kind", "none")), "auc": num(reference.get("auc"))}
    if reference.get("model_version") is not None:
        ref_out["model_version"] = str(reference["model_version"])
    return {
        **summary_from_row(row),
        "validation": {str(k): num(v) for k, v in (res.get("validation") or {}).items()},
        "lift": [
            {
                "decile": integer(x.get("decile")) or 0,
                "n": integer(x.get("n")) or 0,
                "default_rate": num(x.get("default_rate")) or 0.0,
                "mean_pd": num(x.get("mean_pd")) or 0.0,
                "lift": num(x.get("lift")) or 0.0,
                "cum_capture": num(x.get("cum_capture")) or 0.0,
            }
            for x in (res.get("lift") or [])
        ],
        "calibration": [
            {
                "bin": integer(x.get("bin")) or 0,
                "n": integer(x.get("n")) or 0,
                "predicted": num(x.get("predicted")) or 0.0,
                "observed": num(x.get("observed")) or 0.0,
            }
            for x in (res.get("calibration_table") or [])
        ],
        "time_slices": {str(k): num(v) or 0.0 for k, v in (res.get("time_slices") or {}).items()},
        "segments": {str(k): num(v) or 0.0 for k, v in (res.get("segments") or {}).items()},
        "thin_file_auc": num(res.get("thin_file_auc")),
        "score_psi": num(res.get("score_psi_train_val")),
        "checks": {str(k): bool(v) for k, v in (res.get("checks") or {}).items()},
        "leakage": [
            {
                "column": str(x.get("column")),
                "risk": str(x.get("risk", "low")),
                "reasons": [str(r) for r in (x.get("reasons") or [])],
            }
            for x in (res.get("leakage") or [])
        ],
        "fairness": {
            "cutoff_pd": num(fair.get("cutoff_pd")),
            "min_air": num(fair.get("min_air")),
            "n": integer(fair.get("n")),
            "classes": classes,
        },
        "proxies_flagged": [str(x) for x in (res.get("proxies_flagged") or [])],
        "proxy_detail": res.get("proxy_detail") or {},
        "prohibited_features_used": [str(x) for x in (res.get("prohibited_features_used") or [])],
        "best_known": res.get("best_known") or None,
        "versions": {str(k): str(v) for k, v in (res.get("versions") or {}).items()} or None,
        "reason_codes": {
            "quality": res.get("reason_code_quality") or {},
            "sample": [
                {
                    "application_id": str(x.get("application_id")),
                    "rank": integer(x.get("rank")) or 0,
                    "feature": str(x.get("feature")),
                    "reason_text": str(x.get("reason_text", "")),
                }
                for x in (res.get("reason_code_sample") or [])
            ],
        },
        "feature_importance": feature_importance(res),
        "model": {
            "model_type": str(model.get("model_type", "")),
            "features": [str(x) for x in (model.get("features") or [])],
            "engineered": [str(x) for x in (model.get("engineered") or [])],
        },
        "reference": ref_out,
    }


def feature_importance(res: dict) -> list[dict]:
    imp = res.get("feature_importance") or {}
    items = [(str(k), num(v) or 0.0) for k, v in imp.items()]
    return [{"feature": k, "share": v} for k, v in sorted(items, key=lambda kv: kv[1], reverse=True)]


# ---------------------------------------------------------------------------------------------------------- gates
@ttl_cache(30)
def gates() -> pd.DataFrame:
    """Scalar columns of every gate result plus its checks, newest first."""
    df = read_table(deps.ui_store(), "ops", "gate_results", ts=["ts"])
    if df.empty:
        return df
    df = df.sort_values("ts", ascending=False).reset_index(drop=True)
    df["checks"] = [
        {str(k): bool(v) for k, v in ((loads(x, {}) or {}).get("checks") or {}).items()} for x in col(df, "result_json")
    ]
    return df.drop(columns=["result_json"], errors="ignore")


def gate_summary(r: dict) -> dict:
    return {
        "gate_id": str(r["gate_id"]),
        "candidate_ref": str(r["candidate_ref"]),
        "ts": iso(r["ts"]),
        "passed": bool(boolean(r.get("passed"))),
        "holdout_auc": num(r.get("holdout_auc")) or 0.0,
        "reference_holdout_auc": num(r.get("reference_holdout_auc")) or 0.0,
        "checks": r.get("checks") or {},
    }


def latest_gate_row(candidate_ref: str) -> dict | None:
    df = gates()
    if df.empty:
        return None
    hit = df[df["candidate_ref"] == candidate_ref]
    return None if hit.empty else hit.iloc[0].to_dict()


def holdout_used(version: str | None) -> int:
    df = gates()
    if df.empty or not version:
        return 0
    return int((df["definition_version"] == version).sum())


def holdout_budget() -> int:
    return int(config.budgets().get("holdout", {}).get("max_gate_evaluations_per_definition", 0))


# ------------------------------------------------------------------------------------------------------ approvals
@ttl_cache(30)
def promotion_approvals() -> pd.DataFrame:
    """ops.approvals (promotion decisions), newest first."""
    df = read_table(deps.ui_store(), "ops", "approvals", ts=["ts"])
    return df.sort_values("ts", ascending=False).reset_index(drop=True) if len(df) else df


def approval_record(r: dict) -> dict:
    return {
        "approval_id": str(r["approval_id"]),
        "kind": "promotion",
        "ref": str(r["candidate_ref"]),
        "definition_version": str(r.get("definition_version") or ""),
        "decision": str(r.get("decision") or ""),
        "approver": str(r.get("approver") or ""),
        "rationale": str(text(r.get("rationale")) or ""),
        "ts": iso(r["ts"]),
    }


def approvals_for(candidate_ref: str) -> list[dict]:
    df = promotion_approvals()
    if df.empty:
        return []
    return [approval_record(r) for r in df[df["candidate_ref"] == candidate_ref].to_dict("records")]


def latest_approval_row(candidate_ref: str) -> dict | None:
    df = promotion_approvals()
    if df.empty:
        return None
    hit = df[df["candidate_ref"] == candidate_ref]
    return None if hit.empty else hit.iloc[0].to_dict()


@ttl_cache(30)
def definition_approval_records() -> list[dict]:
    df = read_table(deps.ui_store(), "ops", "definition_approvals", ts=["approved_at"])
    out = []
    for r in df.to_dict("records") if len(df) else []:
        out.append(
            {
                "approval_id": str(r["approval_id"]),
                "kind": "definition",
                "ref": str(r["definition_version"]),
                "definition_version": str(r["definition_version"]),
                "decision": "approve",
                "approver": str(r.get("approved_by") or ""),
                "rationale": str(text(r.get("plan_summary")) or "")[:20000],
                "ts": iso(r["approved_at"]),
            }
        )
    return out


def approval_history() -> list[dict]:
    """Promotion and definition approvals together, newest first."""
    pr = promotion_approvals()
    records = [approval_record(r) for r in pr.to_dict("records")] if len(pr) else []
    records += definition_approval_records()
    return sorted(records, key=lambda x: x["ts"] or "", reverse=True)
