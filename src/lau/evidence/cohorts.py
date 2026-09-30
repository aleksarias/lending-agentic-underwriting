"""Bank-statement (cash-flow) cohort summaries -> `ops.cashflow_cohorts`.

Aggregates the `cf_*` features of `curated.applications` by origination quarter over ALL applications (approved and
declined: this is the through-the-door population). Only aggregates leave the harness: the console never reads
applicant-level rows. Written only if the lake has the cash-flow columns.
"""

from __future__ import annotations

import pandas as pd

from lau.evidence import schemas
from lau.evidence.context import EvidenceContext
from lau.evidence.outcomes import quarter_label

SOURCE_COLUMNS = [
    "cf_income_mean_6m",
    "cf_income_cv_6m",
    "cf_expense_to_income_6m",
    "cf_min_balance_6m",
    "cf_nsf_count_6m",
    "cf_overdraft_txn_count_6m",
    "cf_housing_on_time_share_6m",
]


def _positive_share(x: pd.Series) -> float:
    """Share of applicants with a count above zero among those that have the field at all."""
    x = pd.to_numeric(x, errors="coerce").dropna()
    return float((x > 0).mean()) if len(x) else float("nan")


def summarize(apps: pd.DataFrame) -> pd.DataFrame:
    """One row per origination quarter: n, mean income, medians of volatility/expense ratio/min balance, NSF and
    overdraft incidence, mean on-time housing share."""
    g = apps.assign(cohort=quarter_label(apps["origination_month"])).groupby("cohort")
    out = pd.DataFrame(
        {
            "n": g.size(),
            "income_mean": g["cf_income_mean_6m"].mean(),
            "income_cv_median": g["cf_income_cv_6m"].median(),
            "expense_to_income_median": g["cf_expense_to_income_6m"].median(),
            "min_balance_median": g["cf_min_balance_6m"].median(),
            "nsf_rate": g["cf_nsf_count_6m"].apply(_positive_share),
            "overdraft_share": g["cf_overdraft_txn_count_6m"].apply(_positive_share),
            "housing_on_time_mean": g["cf_housing_on_time_share_6m"].mean(),
        }
    )
    return out.reset_index()


def compute(ctx: EvidenceContext) -> pd.DataFrame:
    st = ctx.store
    table = st.fq("curated", "applications")
    present = set(st.query(f"SELECT * FROM {table} LIMIT 0").columns)
    missing = [c for c in SOURCE_COLUMNS if c not in present]
    if missing:
        ctx.log(f"cashflow: curated.applications has no {missing}; nothing written")
        return schemas.conform("cashflow_cohorts", pd.DataFrame())
    apps = st.read_table("curated", "applications", columns=["origination_month", *SOURCE_COLUMNS])
    out = summarize(apps)
    out.insert(0, "run_id", ctx.run_id)
    out.insert(0, "computed_at", ctx.computed_at)
    ctx.log(f"cashflow: {len(out)} quarterly cohort(s) from {len(apps):,} applications")
    return schemas.conform("cashflow_cohorts", out)
