"""Fairness / disparate-impact testing with pluggable protected-class definitions + proxy detection.

Protected attributes are read by the harness only (raw.protected_attributes); agents receive aggregated results.
Approval is simulated as "approve the lowest-PD `approval_rate` share" on the through-the-door population of the
evaluation window (approved AND declined applicants), because the model would be applied to all of them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lau.harness.metrics import univariate_auc


def protected_frame(store) -> pd.DataFrame:
    return store.query(f"SELECT * FROM {store.fq('raw', 'protected_attributes')}")


def adverse_impact(scores: pd.DataFrame, protected: pd.DataFrame, classes: dict, approval_rate: float) -> dict:
    """scores: application_id, pd. Returns per-class approval rates and AIR (min protected/reference)."""
    df = scores.merge(protected, on="application_id", how="inner")
    cutoff = np.quantile(df["pd"], approval_rate)
    df["approved_sim"] = df["pd"] <= cutoff
    out: dict = {"cutoff_pd": float(cutoff), "n": int(len(df)), "classes": {}}
    for cname, spec in classes.items():
        col = spec["column"]
        if col not in df:
            continue
        g = df[col].astype(str)
        rates = df.groupby(g)["approved_sim"].mean()
        ref = str(spec["reference_group"])
        ref_rate = float(rates.get(ref, np.nan))
        airs = {
            str(grp): float(rates[str(grp)] / ref_rate) if ref_rate else np.nan
            for grp in spec["protected_groups"]
            if str(grp) in rates
        }
        mean_pd = df.groupby(g)["pd"].mean()
        out["classes"][cname] = {
            "approval_rates": {k: float(v) for k, v in rates.items()},
            "reference_group": ref,
            "air": airs,
            "min_air": float(min(airs.values())) if airs else np.nan,
            "mean_pd": {k: float(v) for k, v in mean_pd.items()},
        }
    out["min_air"] = float(np.nanmin([c["min_air"] for c in out["classes"].values()])) if out["classes"] else np.nan
    return out


def proxy_scores(features: pd.DataFrame, protected: pd.DataFrame, classes: dict) -> pd.DataFrame:
    """AUC of each feature alone predicting protected-group membership.

    Scored both pooled (any protected group vs everyone else) and per group (that group vs the reference group),
    because a feature that tracks one group can be diluted below the threshold when groups are pooled.
    """
    df = features.merge(protected, on="application_id", how="inner")
    rows = []
    for cname, spec in classes.items():
        col = spec["column"]
        if col not in df:
            continue
        g = df[col].astype(str)
        groups = [str(x) for x in spec["protected_groups"]]
        comparisons = [("pooled", np.ones(len(df), bool), g.isin(groups).to_numpy())]
        ref = str(spec["reference_group"])
        for grp in groups:
            keep = g.isin([grp, ref]).to_numpy()
            if (g == grp).sum() >= 50:
                comparisons.append((grp, keep, (g == grp).to_numpy()))
        for f in features.columns:
            if f == "application_id":
                continue
            best, best_grp = 0.0, None
            for grp, keep, member in comparisons:
                a = univariate_auc(df.loc[keep, f], member[keep].astype(int))
                if a == a and a > best:
                    best, best_grp = a, grp
            rows.append({"feature": f, "protected_class": cname, "protected_group": best_grp, "proxy_auc": best})
    return pd.DataFrame(rows)


def proxy_summary(proxy: pd.DataFrame, threshold: float) -> dict[str, dict]:
    if proxy.empty:
        return {}
    best = proxy.sort_values("proxy_auc", ascending=False).groupby("feature").head(1)
    return {
        r["feature"]: {
            "proxy_auc": float(r["proxy_auc"]),
            "protected_class": r["protected_class"],
            "protected_group": r.get("protected_group"),
            "flag": bool(r["proxy_auc"] > threshold),
        }
        for r in best.to_dict("records")
    }
