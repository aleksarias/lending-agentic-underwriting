"""Adverse-action reason codes from per-feature log-odds contributions (TreeSHAP for GBMs, linear terms for LR).

For each applicant who would be declined, the top-N features that pushed the PD UP are the principal reasons.
Quality checks: coverage, use of prohibited/proxy features in reasons, reason concentration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def reason_codes(
    model, df: pd.DataFrame, declined_mask: np.ndarray, top_n: int, descriptions: dict[str, str] | None = None
) -> pd.DataFrame:
    descriptions = descriptions or {}
    sub = df.loc[declined_mask]
    if sub.empty:
        return pd.DataFrame(columns=["application_id", "rank", "feature", "contribution", "reason_text"])
    contrib = model.contributions(sub)
    rows = []
    vals = contrib.to_numpy()
    cols = np.array(contrib.columns)
    order = np.argsort(-vals, axis=1)[:, :top_n]
    app_ids = sub["application_id"].to_numpy()
    for i in range(len(sub)):
        for rank, j in enumerate(order[i], start=1):
            if vals[i, j] <= 0:
                break
            f = cols[j]
            rows.append(
                {
                    "application_id": app_ids[i],
                    "rank": rank,
                    "feature": f,
                    "contribution": float(vals[i, j]),
                    "reason_text": descriptions.get(f, f.replace("_", " ")),
                }
            )
    return pd.DataFrame(rows)


def reason_quality(codes: pd.DataFrame, n_declined: int, top_n: int, flagged_features: set[str]) -> dict:
    if n_declined == 0:
        return {
            "n_declined": 0,
            "coverage_any": 1.0,
            "coverage_full": 1.0,
            "flagged_feature_share": 0.0,
            "top_reason_share": 0.0,
        }
    per_app = codes.groupby("application_id").size() if not codes.empty else pd.Series(dtype=int)
    full = float((per_app >= top_n).sum() / n_declined)  # informational: Reg B asks for principal reasons, up to 4
    any_ = float((per_app >= 1).sum() / n_declined)
    flagged = float(codes["feature"].isin(flagged_features).mean()) if not codes.empty else 0.0
    top1 = codes[codes["rank"] == 1]["feature"].value_counts(normalize=True) if not codes.empty else pd.Series()
    return {
        "n_declined": int(n_declined),
        "coverage_any": any_,
        "coverage_full": full,
        "flagged_feature_share": flagged,
        "top_reason_share": float(top1.iloc[0]) if len(top1) else 0.0,
        "top_reasons": {k: float(v) for k, v in top1.head(8).items()},
    }
