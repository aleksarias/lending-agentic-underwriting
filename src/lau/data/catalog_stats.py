"""Data catalog: per-variable stats, missingness, cardinality, drift, leakage and proxy risk; per definition_version.

Rebuilt whenever the definition changes, because a variable's predictiveness and leakage risk depend on the label.
Runs as the harness identity (it reads protected attributes to compute proxy risk; agents only see the flags).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from lau.data.features import META_COLUMNS, is_timestamp_col, prohibited_features
from lau.harness import fairness, leakage, metrics


def build_catalog(
    apps: pd.DataFrame,
    train: pd.DataFrame,
    val: pd.DataFrame,
    lineage: pd.DataFrame,
    protected: pd.DataFrame,
    cfg_leak: dict,
    cfg_fair: dict,
    protected_classes: dict,
    version: str,
) -> pd.DataFrame:
    lin = {r["column_name"]: r for r in lineage.to_dict("records")}
    y = train["label"].to_numpy()
    variables = [c for c in apps.columns if c not in META_COLUMNS and not is_timestamp_col(c)]
    train_months = sorted(train["origination_month"].unique())
    early = train[train["origination_month"].isin(train_months[: max(1, len(train_months) // 3)])]

    prox = fairness.proxy_summary(
        fairness.proxy_scores(
            apps[["application_id", *variables]].sample(min(len(apps), 20000), random_state=0),
            protected,
            protected_classes,
        ),
        cfg_fair["proxy_auc_flag"],
    )
    rows = []
    for v in variables:
        s = apps[v]
        is_num = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        finding = leakage.check_column(train, v, y, cfg_leak, lin.get(v))
        if is_num:
            x = pd.to_numeric(s, errors="coerce")
            q = x.quantile([0.01, 0.5, 0.99])
            stats = {
                "mean": float(x.mean()),
                "std": float(x.std()),
                "p01": float(q.iloc[0]),
                "p50": float(q.iloc[1]),
                "p99": float(q.iloc[2]),
            }
            drift = metrics.psi(pd.to_numeric(early[v], errors="coerce"), pd.to_numeric(val[v], errors="coerce"))
            top = {}
        else:
            stats = {"mean": np.nan, "std": np.nan, "p01": np.nan, "p50": np.nan, "p99": np.nan}
            drift = metrics.psi_categorical(early[v], val[v])
            top = s.astype(str).value_counts(normalize=True).head(5).round(4).to_dict()
        pinfo = prox.get(v, {})
        rows.append(
            {
                "definition_version": version,
                "variable": v,
                "variable_kind": "base",
                "dtype": "numeric" if is_num else "categorical",
                "description": (lin.get(v) or {}).get("description", ""),
                "source_system": (lin.get(v) or {}).get("source_system", ""),
                "availability": (lin.get(v) or {}).get("available_at", ""),
                "missing_rate": float(s.isna().mean()),
                "cardinality": int(s.nunique(dropna=True)),
                **stats,
                "top_values_json": json.dumps(top),
                "univariate_auc_train": finding.single_feature_auc
                if finding.single_feature_auc is not None
                else np.nan,
                "drift_psi_early_train_vs_val": float(drift),
                "ts_after_decision_share": finding.ts_after_decision_share
                if finding.ts_after_decision_share is not None
                else np.nan,
                "leakage_risk": finding.risk,
                "leakage_reasons": "; ".join(finding.reasons),
                "proxy_auc": float(pinfo.get("proxy_auc", np.nan)),
                "proxy_class": pinfo.get("protected_class", ""),
                "proxy_risk": "high" if pinfo.get("flag") else "low",
                "prohibited": v in prohibited_features(),
            }
        )
    return pd.DataFrame(rows)
