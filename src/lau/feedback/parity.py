"""Training-serving parity: are the inputs the decision API sees distributed like the data models were trained on?

The release check (`lau decision check parity`) proves the served code computes features exactly like training for
the same applications. This evidence step watches the other half, the inputs themselves: for every feature of the
serving model (plus the cash-flow features), the population stability index between training applications and the
last 30 days of decisions, null rates and means. A shifted feature is a reason to look before trusting the model.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from lau.settings import get_settings

WINDOW_DAYS = 30
TRAINING_SAMPLE = 20_000


def _serving_features(ctx) -> list[str]:
    from lau.modeling import registry_io

    serving = registry_io.serving_model("harness")
    if not serving:
        return []
    try:
        model = registry_io.load_pd_model(
            f"models:/{registry_io.production_model_name()}/{serving['model_version']}", "harness"
        )
    except Exception as e:  # noqa: BLE001 - parity of the cash-flow features still runs
        ctx.log(f"  serving parity: serving model not loadable ({type(e).__name__}); cash-flow features only")
        return []
    return list(model.raw_inputs)


def compute(ctx) -> pd.DataFrame:
    """ops.serving_parity: one row per feature."""
    from lau.evidence.context import EvidenceNotReadyError
    from lau.harness.metrics import psi, psi_categorical
    from lau.synth.cashflow import CASHFLOW_FEATURES

    st = ctx.store
    if not (st.table_exists("ops", "decisions") and st.table_exists("curated", "decision_inputs")):
        raise EvidenceNotReadyError("no decisions yet")
    t = st.fq("ops", "decisions")
    served = st.query(
        f"SELECT i.application_json, i.cashflow_json FROM {st.fq('curated', 'decision_inputs')} i JOIN {t} d "
        "ON i.decision_id = d.decision_id WHERE NOT d.is_test "
        f"AND d.decided_at >= (SELECT max(decided_at) FROM {t}) - INTERVAL {WINDOW_DAYS} DAYS"
    )
    if served.empty:
        raise EvidenceNotReadyError("no decisions in the window")
    apps = pd.DataFrame([json.loads(a) if a else {} for a in served["application_json"]])
    cf = pd.DataFrame([json.loads(c) if c else {} for c in served["cashflow_json"]])
    served_frame = pd.concat([apps.drop(columns=[c for c in cf.columns if c in apps.columns]), cf], axis=1)
    train = st.query(f"SELECT * FROM {st.fq('curated', 'applications')} LIMIT {TRAINING_SAMPLE}")
    model_features = set(_serving_features(ctx))
    features = [f for f in sorted(model_features | set(CASHFLOW_FEATURES)) if f in train.columns]
    mon = get_settings().thresholds["monitoring"]
    rows = []
    for f in features:
        a = served_frame[f] if f in served_frame else pd.Series([np.nan] * len(served_frame))
        b = train[f]
        numeric = pd.api.types.is_numeric_dtype(b) and not pd.api.types.is_bool_dtype(b)
        if numeric:
            av = pd.to_numeric(a, errors="coerce").to_numpy(float)
            bv = pd.to_numeric(b, errors="coerce").to_numpy(float)
            value = psi(bv[~np.isnan(bv)], av[~np.isnan(av)]) if (~np.isnan(av)).any() else None
            mean_train, mean_served = float(np.nanmean(bv)), float(np.nanmean(av)) if (~np.isnan(av)).any() else None
        else:
            value = psi_categorical(b.astype(str), a.astype(str))
            mean_train = mean_served = None
        status = (
            "missing"
            if f not in served_frame
            else (
                "alert"
                if value is not None and value >= mon["psi_alert"]
                else "warn"
                if value is not None and value >= mon["psi_warn"]
                else "ok"
            )
        )
        rows.append(
            {
                "feature": f,
                "kind": "numeric" if numeric else "categorical",
                "in_serving_model": f in model_features,
                "psi": value,
                "status": status,
                "null_rate_train": float(b.isna().mean()),
                "null_rate_served": float(pd.isna(a).mean()),
                "mean_train": mean_train,
                "mean_served": mean_served,
                "n_served": len(served_frame),
            }
        )
    out = pd.DataFrame(rows)
    out.insert(0, "window_days", WINDOW_DAYS)
    out.insert(0, "run_id", ctx.run_id)
    out.insert(0, "computed_at", ctx.computed_at)
    return out
