"""Production labels and evidence: how the loans the decision API approved actually performed.

Labels come from the feed's current view (corrections applied) under the active definition of default, by the same
label builder as training. A loan counts once its observation window has passed and it is not excluded ("matured").
Production evidence compares each decision's predicted PD with the outcome on matured loans, by deciding model,
vintage and risk band. Declined applications have no outcome: this measures calibration and ranking among approved
loans only; the selection bias stays (docs/reject-inference.md).

Maturation trigger (daily job, after the feed): when enough new loans mature, ops.maturation_events records it and an
improvement cycle is queued, as monitoring alerts do.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.settings import get_settings
from lau.store import get_store

PERF_COLUMNS = [
    "loan_id",
    "application_id",
    "mob",
    "period_month",
    "status",
    "dpd",
    "balance",
    "past_due_amount",
    "scheduled_payment",
    "payment_amount",
    "charge_off_flag",
    "bankruptcy_flag",
    "settlement_flag",
    "forbearance_flag",
    "payoff_flag",
    "fraud_flag",
    "deceased_flag",
]


class NoProductionDataError(RuntimeError):
    pass


def book(store=None) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """(loans, performance in raw.performance shape, as-of month) for the production loan book."""
    st = store or get_store("harness")
    if not (st.table_exists("curated", "loan_bookings") and st.table_exists("curated", "loan_performance_current")):
        raise NoProductionDataError("no loan status feed has been ingested yet")
    loans = st.query(
        "SELECT b.loan_id, b.application_id, b.decision_id, b.booked_month AS origination_month, "
        f"d.decided_at AS decision_ts FROM {st.fq('curated', 'loan_bookings')} b "
        f"JOIN {st.fq('ops', 'decisions')} d ON b.decision_id = d.decision_id"
    ).drop_duplicates("loan_id")
    cur = st.query(f"SELECT * FROM {st.fq('curated', 'loan_performance_current')}")
    if loans.empty or cur.empty:
        raise NoProductionDataError("no production loan has reported performance yet")
    booked = loans.set_index("loan_id")["origination_month"]
    cur = cur[cur["loan_id"].isin(booked.index)].copy()
    cur["mob"] = [
        (pd.Period(p, "M") - pd.Period(booked[lid], "M")).n
        for lid, p in zip(cur["loan_id"], cur["period_month"], strict=True)
    ]
    cur["application_id"] = cur["loan_id"].map(loans.set_index("loan_id")["application_id"])
    as_of = str(cur["period_month"].max())
    return loans.reset_index(drop=True), cur[PERF_COLUMNS].reset_index(drop=True), as_of


def labels(defn=None, store=None) -> tuple[pd.DataFrame, str, str]:
    """(labels of the production book under `defn` or the active definition, its version, as-of month)."""
    from lau.definition.label_builder import build_labels
    from lau.definition.registry import active_version, get_definition

    st = store or get_store("harness")
    version = active_version(st)
    defn = defn or get_definition(st, version)
    loans, perf, as_of = book(st)
    return build_labels(perf, loans, defn, as_of), version, as_of


def matured(lab: pd.DataFrame) -> pd.DataFrame:
    return lab[lab["label"].notna() & ~lab["is_excluded"].astype(bool) & ~lab["is_censored"].astype(bool)]


def maturation_check(log=print) -> dict:
    """Record how many production loans have matured; queue an improvement cycle when enough new ones have."""
    st = get_store("harness")
    try:
        lab, version, as_of = labels(store=st)
    except NoProductionDataError as e:
        log(f"maturation: {e}")
        return {"matured": 0, "new": 0, "queued": False}
    n = len(matured(lab))
    before = 0
    if st.table_exists("ops", "maturation_events"):
        prev = st.query(
            f"SELECT matured FROM {st.fq('ops', 'maturation_events')} WHERE definition_version = '{version}' "
            "ORDER BY recorded_at DESC LIMIT 1"
        )
        before = int(prev["matured"].iloc[0]) if len(prev) else 0
    new = max(n - before, 0)
    need = int(get_settings().feedback["production"]["min_new_matured_to_queue"])
    queued = new >= need
    now = datetime.now(UTC).replace(tzinfo=None)
    row = {
        "recorded_at": now,
        "definition_version": version,
        "as_of_month": as_of,
        "booked": len(lab),
        "matured": n,
        "new_matured": new,
        "queued_cycle": queued,
    }
    st.write_df("ops", "maturation_events", pd.DataFrame([row]), mode="append")
    alert = calibration_alert(lab, version, now)
    queued = queued or (alert is not None and alert["severity"] == "high")
    if queued:
        st.write_df(
            "ops",
            "cycle_queue",
            pd.DataFrame(
                [
                    {
                        "requested_at": now,
                        "definition_version": version,
                        "reason": "production_calibration"
                        if alert and alert["severity"] == "high"
                        else "loans_matured",
                        "status": "queued",
                    }
                ]
            ),
            mode="append",
        )
    log(
        f"maturation: {n} of {len(lab)} production loans matured under {version[:8]} ({new} new)"
        + ("; improvement cycle queued" if queued else "")
    )
    return {"matured": n, "new": new, "queued": queued}


def calibration_alert(lab: pd.DataFrame, version: str, ts: datetime) -> dict | None:
    """Matured production loans defaulting well above or below the PD they were approved at -> ops.alerts.

    Same rule as monitoring's observed-versus-expected check (thresholds.monitoring.default_rate_rel_tol); high when
    off by more than twice the tolerance, which also queues a cycle. The alert is current until the next check.
    """
    st = get_store("harness")
    dec = st.query(
        f"SELECT application_id, probability_of_default FROM {st.fq('ops', 'decisions')} "
        "WHERE NOT is_test AND probability_of_default IS NOT NULL"
    ).drop_duplicates("application_id", keep="last")
    m = matured(lab).merge(dec, on="application_id")
    if len(m) < int(get_settings().feedback["production"]["min_matured_for_auc"]):
        return None
    observed, expected = float(m["label"].astype(int).mean()), float(m["probability_of_default"].mean())
    tol = float(get_settings().thresholds["monitoring"]["default_rate_rel_tol"])
    gap = (observed - expected) / expected if expected > 0 else 0.0
    if abs(gap) <= tol:
        return None
    alert = {
        "kind": "production_default_rate",
        "subject": "matured_loans",
        "value": gap,
        "severity": "high" if abs(gap) > 2 * tol else "medium",
        "ts": ts,
        "definition_version": version,
    }
    st.write_df("ops", "alerts", pd.DataFrame([alert]), mode="append")
    return alert


# ---- the evidence step ----------------------------------------------------------------------------------------------
def _auc(y: np.ndarray, p: np.ndarray, min_n: int) -> float | None:
    if len(y) < min_n or len(set(y.tolist())) < 2:
        return None
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(y, p))


def _summary(g: pd.DataFrame, min_n: int) -> dict:
    m = g[g["matured"]]
    scored = m[m["probability_of_default"].notna()]
    y = scored["label"].astype(int).to_numpy()
    p = scored["probability_of_default"].astype(float).to_numpy()
    realized = float(m["label"].astype(int).mean()) if len(m) else None
    predicted = float(p.mean()) if len(p) else None
    return {
        "n_booked": len(g),
        "n_matured": len(m),
        "n_defaults": int(m["label"].astype(int).sum()) if len(m) else 0,
        "realized_rate": realized,
        "predicted_pd": predicted,
        "calibration_ratio": (realized / predicted) if realized is not None and predicted else None,
        "auc": _auc(y, p, min_n),
        "brier": float(np.mean((p - y) ** 2)) if len(p) else None,
    }


def compute(ctx) -> pd.DataFrame:
    """ops.production_evidence: predicted against realized, by deciding model, vintage and risk band."""
    from lau.evidence.context import EvidenceNotReadyError

    st = ctx.store
    try:
        lab, version, as_of = labels(store=st)
    except NoProductionDataError as e:
        raise EvidenceNotReadyError(str(e)) from e
    dec = st.query(
        f"SELECT application_id, model_version, probability_of_default, risk_band FROM {st.fq('ops', 'decisions')} "
        "WHERE NOT is_test"
    ).drop_duplicates("application_id", keep="last")
    df = lab.merge(dec, on="application_id", how="left")
    df["matured"] = df["label"].notna() & ~df["is_excluded"].astype(bool) & ~df["is_censored"].astype(bool)
    df["model_version"] = df["model_version"].fillna("legacy")
    min_n = int(get_settings().feedback["production"]["min_matured_for_auc"])
    rows = [{"scope": "overall", "key": "all", "model_version": None, **_summary(df, min_n)}]
    for mv, g in df.groupby("model_version"):
        rows.append({"scope": "model", "key": str(mv), "model_version": str(mv), **_summary(g, min_n)})
    for vintage, g in df.groupby("origination_month"):
        rows.append({"scope": "vintage", "key": str(vintage), "model_version": None, **_summary(g, min_n)})
    for band, g in df[df["risk_band"].notna()].groupby("risk_band"):
        rows.append({"scope": "band", "key": str(band), "model_version": None, **_summary(g, min_n)})
    out = pd.DataFrame(rows)
    out.insert(0, "as_of_month", as_of)
    out.insert(0, "definition_version", version)
    out.insert(0, "run_id", ctx.run_id)
    out.insert(0, "computed_at", ctx.computed_at)
    return out
