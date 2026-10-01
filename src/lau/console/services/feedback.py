"""The loan status feed, production evidence, fairness on actual decisions and training-serving parity, as the
console shows them. Only ops tables (aggregates and file-level records): the loan book itself lives in curated, which
the console identity cannot read.
"""

from __future__ import annotations

import pandas as pd

from lau.console import deps
from lau.console.util import boolean, integer, iso, num, query, table_exists, text, ttl_cache, unavailable


def _latest_run(table: str, ts: tuple[str, ...] = ("computed_at",)) -> pd.DataFrame:
    st = deps.ui_store()
    if not table_exists(st, "ops", table):
        return pd.DataFrame()
    t = st.fq("ops", table)
    return query(
        st, f"SELECT * FROM {t} WHERE run_id = (SELECT run_id FROM {t} ORDER BY computed_at DESC LIMIT 1)", ts=ts
    )


# ---- feed ----------------------------------------------------------------------------------------------------------
@ttl_cache(15)
def feed_live() -> dict | None:
    st = deps.ui_store()
    if not table_exists(st, "ops", "feed_files"):
        return None
    files = query(st, f"SELECT * FROM {st.fq('ops', 'feed_files')} ORDER BY ingested_at DESC", ts=["ingested_at"])
    latest = files.drop_duplicates("feed_file", keep="first")
    held = latest[latest["status"] == "held"]["feed_file"].astype(str).tolist()
    out: dict = {
        "files": [
            {
                "feed_file": str(r["feed_file"]),
                "file_month": text(r.get("file_month")),
                "status": str(r["status"]),
                "records": integer(r.get("records")) or 0,
                "accepted": integer(r.get("accepted")) or 0,
                "quarantined": integer(r.get("quarantined")) or 0,
                "restatements": integer(r.get("restatements")) or 0,
                "ingested_at": iso(r.get("ingested_at")),
                "released_by": text(r.get("released_by")),
            }
            for r in files.head(36).to_dict("records")
        ],
        "held": held,
        "quarantine": {"total": 0, "by_reason": [], "recent": []},
        "restatements": {"total": 0, "recent": []},
        "book": [],
        "maturation": [],
    }
    if table_exists(st, "ops", "feed_quarantine"):
        q = query(st, f"SELECT * FROM {st.fq('ops', 'feed_quarantine')} ORDER BY ingested_at DESC", ts=["ingested_at"])
        reasons = q["reasons"].astype(str).str.split("; ").explode()
        out["quarantine"] = {
            "total": len(q),
            "by_reason": [{"reason": str(k), "n": int(v)} for k, v in reasons.value_counts().head(10).items()],
            "recent": [
                {
                    "feed_file": str(r["feed_file"]),
                    "loan_id": text(r.get("loan_id")),
                    "reasons": str(r["reasons"]),
                    "ingested_at": iso(r.get("ingested_at")),
                }
                for r in q.head(20).to_dict("records")
            ],
        }
    if table_exists(st, "ops", "feed_restatements"):
        r = query(
            st, f"SELECT * FROM {st.fq('ops', 'feed_restatements')} ORDER BY ingested_at DESC", ts=["ingested_at"]
        )
        out["restatements"] = {
            "total": len(r),
            "recent": [
                {
                    "loan_id": str(x["loan_id"]),
                    "period_month": str(x["period_month"]),
                    "reported_month": str(x["reported_month"]),
                    "dpd_before": integer(x.get("dpd_before")),
                    "dpd_after": integer(x.get("dpd_after")),
                }
                for x in r.head(20).to_dict("records")
            ],
        }
    if table_exists(st, "ops", "feed_summary"):
        b = query(st, f"SELECT * FROM {st.fq('ops', 'feed_summary')} ORDER BY period_month")
        out["book"] = [
            {k: (str(v) if k == "period_month" else num(v)) for k, v in row.items()} for row in b.to_dict("records")
        ]
    if table_exists(st, "ops", "maturation_events"):
        m = query(st, f"SELECT * FROM {st.fq('ops', 'maturation_events')} ORDER BY recorded_at", ts=["recorded_at"])
        out["maturation"] = [
            {
                "recorded_at": iso(x["recorded_at"]),
                "definition_version": str(x["definition_version"]),
                "as_of_month": str(x["as_of_month"]),
                "booked": integer(x["booked"]) or 0,
                "matured": integer(x["matured"]) or 0,
                "new_matured": integer(x["new_matured"]) or 0,
                "queued_cycle": bool(boolean(x["queued_cycle"])),
            }
            for x in m.to_dict("records")
        ]
    return out


# ---- production evidence ------------------------------------------------------------------------------------------
def _prod_row(r: dict) -> dict:
    return {
        "key": str(r["key"]),
        "model_version": text(r.get("model_version")),
        "n_booked": integer(r.get("n_booked")) or 0,
        "n_matured": integer(r.get("n_matured")) or 0,
        "n_defaults": integer(r.get("n_defaults")) or 0,
        "realized_rate": num(r.get("realized_rate")),
        "predicted_pd": num(r.get("predicted_pd")),
        "calibration_ratio": num(r.get("calibration_ratio")),
        "auc": num(r.get("auc")),
        "brier": num(r.get("brier")),
    }


def production_evidence() -> dict:
    df = _latest_run("production_evidence")
    if df.empty:
        return unavailable(
            "No production loan has matured yet. Loans the decision API approved report their status through the loan "
            "status feed; once a loan's observation window has passed, its outcome is compared with the PD it was "
            "approved at.",
            ["Decisions on (synthetic) traffic", "The loan status feed", "Loans past the definition's window"],
        )
    rows = df.to_dict("records")
    by = {s: [_prod_row(r) for r in rows if r["scope"] == s] for s in ("overall", "model", "vintage", "band")}
    return {
        "available": True,
        "computed_at": iso(df["computed_at"].max()),
        "definition_version": str(df["definition_version"].iloc[0]),
        "as_of_month": str(df["as_of_month"].iloc[0]),
        "overall": by["overall"][0] if by["overall"] else None,
        "models": by["model"],
        "vintages": sorted(by["vintage"], key=lambda r: r["key"]),
        "bands": sorted(by["band"], key=lambda r: r["key"]),
    }


# ---- fairness on decisions -------------------------------------------------------------------------------------------
def decision_fairness() -> dict:
    df = _latest_run("decision_fairness")
    if df.empty:
        return unavailable(
            "No decisions to test yet. Fairness on actual decisions compares approval rates by group once the decision "
            "API has decided applications.",
            ["Decisions on (synthetic) traffic"],
        )
    rows = [
        {
            "attribute": str(r["attribute"]),
            "group": str(r["group"]),
            "method": str(r["method"]),
            "reference_group": str(r["reference_group"]),
            "n": num(r.get("n")),
            "approval_rate": num(r.get("approval_rate")),
            "decline_rate": num(r.get("decline_rate")),
            "air": num(r.get("air")),
            "below_threshold": bool(boolean(r.get("below_threshold"))),
        }
        for r in df.to_dict("records")
    ]
    return {
        "available": True,
        "computed_at": iso(df["computed_at"].max()),
        "window_days": integer(df["window_days"].iloc[0]),
        "n_decisions": integer(df["n_decisions"].iloc[0]),
        "rows": rows,
        "method_note": (
            "Race and ethnicity are estimated from surnames (the BISG method without its geography term, from a "
            "synthetic surname table) and shown next to the synthetic truth, which shows how far the estimate can be "
            "trusted. Age 62+ comes from the application. Counsel must approve the method before real use."
        ),
    }


# ---- training-serving parity -----------------------------------------------------------------------------------------
def serving_parity() -> dict:
    df = _latest_run("serving_parity")
    if df.empty:
        return unavailable(
            "No decisions to compare yet. Parity compares the inputs of the last 30 days of decisions with the "
            "applications models were trained on.",
            ["Decisions on (synthetic) traffic"],
        )
    rows = [
        {
            "feature": str(r["feature"]),
            "kind": str(r["kind"]),
            "in_serving_model": bool(boolean(r.get("in_serving_model"))),
            "psi": num(r.get("psi")),
            "status": str(r["status"]),
            "null_rate_train": num(r.get("null_rate_train")),
            "null_rate_served": num(r.get("null_rate_served")),
            "mean_train": num(r.get("mean_train")),
            "mean_served": num(r.get("mean_served")),
        }
        for r in df.to_dict("records")
    ]
    return {
        "available": True,
        "computed_at": iso(df["computed_at"].max()),
        "window_days": integer(df["window_days"].iloc[0]),
        "n_served": integer(df["n_served"].iloc[0]),
        "rows": sorted(rows, key=lambda r: -(r["psi"] or 0)),
    }
