"""Monitoring: score/feature PSI vs the definition's monitoring baseline, early-indicator and final-outcome checks
as loans mature. Alerts are written to ops.alerts; a high-severity alert enqueues a new improvement cycle.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.definition.label_builder import early_indicator
from lau.definition.labels_io import read_all_labels_for_version
from lau.definition.registry import active_version
from lau.harness import metrics
from lau.modeling import registry_io
from lau.store import get_store


def run_monitor(log=print) -> dict:
    st = get_store("harness")
    version = active_version(st)
    base = st.query(f"SELECT * FROM {st.fq('ops', 'monitoring_baseline')} WHERE definition_version = '{version}'")
    if base.empty:
        raise RuntimeError("no monitoring baseline for the active definition; run the pipeline")
    b = base.iloc[0]
    th = json.loads(b["thresholds_json"])
    model = registry_io.load_pd_model(b["reference_model_uri"], "harness")
    alerts: list[dict] = []

    # 1. score + feature PSI on the newest applications (shadow population)
    new = st.query(f"SELECT * FROM {st.fq('curated', 'new_applications')}")
    p_new = model.predict_pd(new)
    score_psi = metrics.psi_from_edges(json.loads(b["score_edges_json"]), json.loads(b["score_shares_json"]), p_new)
    feat_psi = {
        f: metrics.psi_from_edges(v["edges"], v["shares"], pd.to_numeric(new[f], errors="coerce").dropna())
        for f, v in json.loads(b["feature_baselines_json"]).items()
        if f in new
    }
    for name, val in [("score", score_psi), *feat_psi.items()]:
        if val >= th["psi_alert"]:
            alerts.append({"kind": "psi", "subject": name, "value": val, "severity": "high"})
        elif val >= th["psi_warn"]:
            alerts.append({"kind": "psi", "subject": name, "value": val, "severity": "medium"})

    # 2. outcomes as loans mature: early indicator on recent vintages + final outcomes on newly-mature loans
    perf = st.query(f"SELECT loan_id, mob, dpd FROM {st.fq('raw', 'performance')}")
    apps = st.query(f"SELECT * FROM {st.fq('curated', 'applications')} WHERE approved")
    meta = st.query(
        f"SELECT oot_start, oot_end FROM {st.fq('labels', 'split_meta')} WHERE definition_version = '{version}'"
    ).iloc[0]
    recent = apps[apps["origination_month"] > meta["oot_end"]]
    ei = early_indicator(perf, th["early_indicator_dpd"], th["early_indicator_mob"])
    rec = recent.merge(ei.rename("ei").reset_index(), on="loan_id", how="inner")
    early = {}
    if len(rec) > 100:
        p = model.predict_pd(rec)
        early = {
            "n": int(len(rec)),
            "early_indicator_rate": float(rec["ei"].mean()),
            "mean_pd": float(p.mean()),
            "auc_vs_early_indicator": metrics.auc(rec["ei"].to_numpy(), p),
        }
    labels = read_all_labels_for_version(st, version, "monitor")
    final = labels[(~labels["is_excluded"]) & (~labels["is_censored"])]
    mature = apps.merge(final[["application_id", "label"]], on="application_id")
    mature = mature[mature["origination_month"] >= meta["oot_start"]]
    outcome = {}
    if len(mature) > 100:
        p = model.predict_pd(mature)
        obs, exp = float(mature["label"].mean()), float(p.mean())
        outcome = {
            "n": int(len(mature)),
            "observed_default_rate": obs,
            "expected_default_rate": exp,
            "auc": metrics.auc(mature["label"].to_numpy(), p),
        }
        if exp > 0 and abs(obs - exp) / exp > th["default_rate_rel_tol"]:
            alerts.append(
                {
                    "kind": "default_rate",
                    "subject": "observed_vs_expected",
                    "value": (obs - exp) / exp,
                    "severity": "high",
                }
            )
    ts = datetime.now(UTC)
    if alerts:
        st.write_df(
            "ops",
            "alerts",
            pd.DataFrame([{**a, "ts": ts, "definition_version": version, "value": float(a["value"])} for a in alerts]),
            mode="append",
        )
    triggered = any(a["severity"] == "high" for a in alerts)
    if triggered:
        st.write_df(
            "ops",
            "cycle_queue",
            pd.DataFrame(
                [{"requested_at": ts, "definition_version": version, "reason": "monitoring_alert", "status": "queued"}]
            ),
            mode="append",
        )
    summary = {
        "definition_version": version,
        "reference_model": b["reference_model_uri"],
        "score_psi": score_psi,
        "max_feature_psi": max(feat_psi.values()) if feat_psi else np.nan,
        "early_indicators": early,
        "final_outcomes": outcome,
        "alerts": alerts,
        "cycle_enqueued": triggered,
    }
    st.write_df(
        "ops",
        "monitoring_runs",
        pd.DataFrame([{"ts": ts, "definition_version": version, "summary_json": json.dumps(summary, default=str)}]),
        mode="append",
    )
    log(json.dumps(summary, indent=1, default=str))
    return summary
