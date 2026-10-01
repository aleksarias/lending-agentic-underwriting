"""Console API (screen 12, data catalog and cash flows):
- GET /api/catalog?[def], GET /api/catalog/{variable}?[def]
- GET /api/cashflow/cohorts

The catalog holds per-variable statistics computed by the pipeline (curated.data_catalog); cash-flow cohorts are
aggregates (ops.cashflow_cohorts). No applicant-level rows are read.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

import pandas as pd
from fastapi import HTTPException

from lau.console import deps
from lau.console.services import definitions as defs
from lau.console.util import (
    DEF_PARAM,
    api_router,
    boolean,
    integer,
    iso,
    loads,
    num,
    read_table,
    safe_token,
    sql_str,
    table_exists,
    text,
    ttl_cache,
)

router = api_router()


@ttl_cache(30)
def _catalog(version: str) -> pd.DataFrame:
    return read_table(deps.ui_store(), "curated", "data_catalog", where=f"definition_version = {sql_str(version)}")


def _risk(v, allowed: tuple[str, ...], default: str) -> str:
    s = str(text(v) or default).lower()
    return s if s in allowed else default


def _variable(r: dict) -> dict:
    top = loads(r.get("top_values_json"), None)
    return {
        "variable": str(r["variable"]),
        "dtype": str(text(r.get("dtype")) or ""),
        "description": str(text(r.get("description")) or ""),
        "source_system": str(text(r.get("source_system")) or ""),
        "availability": str(text(r.get("availability")) or ""),
        "missing_rate": num(r.get("missing_rate")),
        "cardinality": integer(r.get("cardinality")),
        "univariate_auc_train": num(r.get("univariate_auc_train")),
        "drift_psi": num(r.get("drift_psi_early_train_vs_val")),
        "leakage_risk": _risk(r.get("leakage_risk"), ("high", "medium", "low"), "low"),
        "leakage_reasons": str(text(r.get("leakage_reasons")) or ""),
        "proxy_risk": _risk(r.get("proxy_risk"), ("high", "low"), "low"),
        "proxy_auc": num(r.get("proxy_auc")),
        "proxy_class": text(r.get("proxy_class")),
        "prohibited": bool(boolean(r.get("prohibited"))),
        "mean": num(r.get("mean")),
        "p01": num(r.get("p01")),
        "p50": num(r.get("p50")),
        "p99": num(r.get("p99")),
        "top_values": {str(k): num(v) or 0.0 for k, v in top.items()} if isinstance(top, dict) else None,
    }


def _version(version: str | None) -> str:
    return defs.resolve_or_404(version)


@router.get("/catalog")
def catalog(version: str | None = DEF_PARAM) -> dict:
    v = _version(version)
    df = _catalog(v) if v else pd.DataFrame()
    rows = [_variable(r) for r in df.sort_values("variable").to_dict("records")] if len(df) else []
    return {"definition_version": v, "definitions": defs.definition_refs(), "variables": rows}


@router.get("/catalog/{variable}")
def variable(variable: str, version: str | None = DEF_PARAM) -> dict:
    if not safe_token(variable):
        raise HTTPException(status_code=400, detail="invalid variable name")
    df = _catalog(_version(version))
    hit = df[df["variable"] == variable] if len(df) else df
    if hit.empty:
        raise HTTPException(status_code=404, detail="unknown variable")
    return _variable(hit.iloc[0].to_dict())


@router.get("/parity")
def parity() -> dict:
    """Training-serving parity of the inputs the decision API saw (ops.serving_parity)."""
    from lau.console.services import feedback

    return feedback.serving_parity()


@router.get("/cashflow/cohorts")
def cashflow_cohorts() -> dict:
    st = deps.ui_store()
    if not table_exists(st, "ops", "cashflow_cohorts"):
        return {"computed_at": None, "cohorts": []}
    t = st.fq("ops", "cashflow_cohorts")
    df = read_table(
        st,
        "ops",
        "cashflow_cohorts",
        where=f"run_id = (SELECT run_id FROM {t} ORDER BY computed_at DESC LIMIT 1)",
        ts=["computed_at"],
    )
    if df.empty:
        return {"computed_at": None, "cohorts": []}
    cols = [
        "income_mean",
        "income_cv_median",
        "expense_to_income_median",
        "min_balance_median",
        "nsf_rate",
        "overdraft_share",
        "housing_on_time_mean",
    ]
    return {
        "computed_at": iso(df["computed_at"].max()),
        "cohorts": [
            {"cohort": str(r["cohort"]), "n": integer(r["n"]) or 0, **{c: num(r.get(c)) for c in cols}}
            for r in df.sort_values("cohort").to_dict("records")
        ],
    }
