"""Console API: GET /api/feed (screen 11, loan status feed).

There is no live servicing feed yet: performance arrives as batch data versions (ops.data_version). Vintage curves
(ops.vintage_curves) show how cohorts mature under each benchmark threshold; label stats show what each definition
counts as eligible and defaulted.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from lau.console import deps
from lau.console.services import definitions as defs
from lau.console.services import ops
from lau.console.util import api_router, integer, iso, num, read_table, short, table_exists, text

router = api_router()

REQUIRES = [
    "Servicing system change feed (loan status, days past due, balance) delivered daily",
    "Lakeflow AUTO CDC bitemporal loan-status table",
    "Data-quality expectations on the feed",
]


def _vintage() -> dict:
    st = deps.ui_store()
    if not table_exists(st, "ops", "vintage_curves"):
        return {"computed_at": None, "dpd_thresholds": [], "cohorts": []}
    t = st.fq("ops", "vintage_curves")
    df = read_table(
        st,
        "ops",
        "vintage_curves",
        where=f"run_id = (SELECT run_id FROM {t} ORDER BY computed_at DESC LIMIT 1)",
        ts=["computed_at"],
    )
    if df.empty:
        return {"computed_at": None, "dpd_thresholds": [], "cohorts": []}
    thresholds = sorted(int(x) for x in df["dpd_threshold"].unique())
    cohorts = []
    for cohort, g in df.groupby("cohort"):
        curves = {}
        for dpd, h in g.groupby("dpd_threshold"):
            h = h.sort_values("mob")
            curves[str(int(dpd))] = [num(x) or 0.0 for x in h["cum_rate"]]
        cohorts.append({"cohort": str(cohort), "n": integer(g["n_loans"].max()) or 0, "curves": curves})
    cohorts.sort(key=lambda c: c["cohort"])
    return {"computed_at": iso(df["computed_at"].max()), "dpd_thresholds": thresholds, "cohorts": cohorts}


@router.get("/feed")
def feed() -> dict:
    data = ops.latest_data_version()
    stats = defs.label_stats_by_version()
    maturation = []
    for ref in defs.definition_refs():
        s = stats.get(ref["version"])
        if not s:
            continue
        maturation.append(
            {
                "definition_version": ref["version"],
                "short": short(ref["version"]) or "",
                "n_eligible": s["n_eligible"],
                "n_default": s["n_default"],
                "default_rate": s["default_rate"],
                "excluded": s["exclusions"],
            }
        )
    return {
        "live": False,
        "reason": (
            "Loan status arrives as batch data versions, not a live feed. Each load replaces the performance "
            "history and triggers a pipeline rebuild."
        ),
        "requires": REQUIRES,
        "performance": {
            "data_version": text(data.get("data_version")) if data else None,
            "as_of_month": text(data.get("as_of_month")) if data else None,
            "loaded_at": iso(data.get("created_at")) if data else None,
            "n_applications": integer(data.get("n_applications")) if data else None,
        },
        "vintage": _vintage(),
        "maturation": maturation,
    }
