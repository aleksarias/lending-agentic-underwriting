"""Realized outcomes of the loan book: definition sensitivity and vintage curves.

`ops.definition_sensitivity`  default rate by origination quarter under every benchmark definition (eligible,
                              uncensored loans): how much the choice of DPD threshold moves "the default rate".
`ops.vintage_curves`          cumulative share of each half-year origination cohort that reached 30 / 60 / 90 DPD by
                              month on book 1..12 (an early-indicator view, not a default label; uses
                              `label_builder.early_indicator`).
"""

from __future__ import annotations

import pandas as pd

from lau.definition.label_builder import early_indicator, months_available
from lau.evidence import schemas
from lau.evidence.context import EvidenceContext, eligible

VINTAGE_DPD = (30, 60, 90)
VINTAGE_MOBS = range(1, 13)


def quarter_label(months: pd.Series) -> pd.Series:
    """'2024-08' -> '2024-Q3'."""
    p = pd.PeriodIndex(months.astype(str), freq="M")
    return pd.Series([f"{q.year}-Q{q.quarter}" for q in p], index=months.index)


def half_label(months: pd.Series) -> pd.Series:
    """'2024-08' -> '2024-H2'."""
    p = pd.PeriodIndex(months.astype(str), freq="M")
    return pd.Series([f"{q.year}-H{1 if q.month <= 6 else 2}" for q in p], index=months.index)


def sensitivity(ctx: EvidenceContext) -> pd.DataFrame:
    rows = []
    for bench in ctx.benchmarks:
        e = eligible(ctx.labels(bench))
        if e.empty:
            continue
        g = e.assign(period=quarter_label(e["origination_month"]), y=e["label"].astype(float)).groupby("period")
        for period, part in g:
            rows.append(
                {
                    "computed_at": ctx.computed_at,
                    "run_id": ctx.run_id,
                    "benchmark_key": bench.key,
                    "benchmark_dpd": bench.dpd,
                    "benchmark_version": bench.version,
                    "period": period,
                    "default_rate": float(part["y"].mean()),
                    "n": int(len(part)),
                }
            )
    ctx.log(f"sensitivity: {len(rows)} (benchmark, quarter) rates")
    return schemas.conform("definition_sensitivity", pd.DataFrame(rows))


def vintage(ctx: EvidenceContext) -> pd.DataFrame:
    """Cohorts of loans with at least 12 months of performance, by half-year of origination."""
    last_mob = max(VINTAGE_MOBS)
    loans = ctx.loans
    mature = loans[months_available(loans["origination_month"], ctx.as_of_month) >= last_mob]
    perf = ctx.perf[ctx.perf["mob"] <= last_mob]
    mature = mature[mature["loan_id"].isin(perf["loan_id"].unique())]  # a loan without any performance has no curve
    cohort = half_label(mature["origination_month"]).set_axis(pd.Index(mature["loan_id"]))
    sizes = cohort.value_counts()
    rows = []
    for dpd in VINTAGE_DPD:
        for mob in VINTAGE_MOBS:
            reached = early_indicator(perf, dpd, mob).reindex(cohort.index).fillna(0)
            rate = reached.groupby(cohort).mean()
            for name, value in rate.items():
                rows.append(
                    {
                        "computed_at": ctx.computed_at,
                        "run_id": ctx.run_id,
                        "cohort": name,
                        "dpd_threshold": dpd,
                        "mob": mob,
                        "cum_rate": float(value),
                        "n_loans": int(sizes[name]),
                    }
                )
    ctx.log(f"vintage: {len(sizes)} half-year cohort(s), {int(sizes.sum()):,} loans with >= {last_mob} months")
    return schemas.conform("vintage_curves", pd.DataFrame(rows))
