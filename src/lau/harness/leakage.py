"""Leakage checks (single implementation used by the data catalog, the harness and the red-team tools).

1. Timestamp: a field whose companion timestamp (`<col>_ts`, or `<stem>_ts` for `<stem>_flag`) is after the
   decision timestamp for more than `post_decision_share_max` of rows.
2. Suspicious single-feature AUC: above `single_feature_auc_max` on training labels.
3. Target-derived: lineage from performance/labels tables, or a target-like name pattern.
4. Lineage: availability 'unknown' or 'post_decision' (risk signal, not an automatic fail).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from lau.harness.metrics import univariate_auc

TARGET_SOURCE_TABLES = {"performance", "labels_all", "labels_active", "oot_labels", "splits"}


@dataclass
class LeakageFinding:
    column: str
    ts_after_decision_share: float | None
    single_feature_auc: float | None
    target_like_name: bool
    lineage_availability: str | None
    target_derived_lineage: bool
    risk: str  # high | medium | low
    reasons: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


def timestamp_column_for(col: str, columns: list[str]) -> str | None:
    cands = [f"{col}_ts"]
    if col.endswith("_flag"):
        cands.append(col[: -len("_flag")] + "_ts")
    return next((c for c in cands if c in columns), None)


def ts_after_decision_share(df: pd.DataFrame, col: str) -> float | None:
    ts_col = timestamp_column_for(col, list(df.columns))
    if ts_col is None or "decision_ts" not in df:
        return None
    ts = pd.to_datetime(df[ts_col], errors="coerce")
    dec = pd.to_datetime(df["decision_ts"], errors="coerce")
    mask = ts.notna() & dec.notna()
    if not mask.any():
        return None
    return float((ts[mask] > dec[mask]).mean())


def check_column(
    df: pd.DataFrame,
    col: str,
    y: np.ndarray | None,
    cfg: dict,
    lineage: dict | None = None,
    source_tables: list[str] | None = None,
) -> LeakageFinding:
    reasons: list[str] = []
    share = ts_after_decision_share(df, col)
    if share is not None and share > cfg["post_decision_share_max"]:
        reasons.append(f"populated after decision for {share:.1%} of rows")
    sfa = univariate_auc(df[col], y) if y is not None and len(np.unique(y)) > 1 else None
    if sfa is not None and not np.isnan(sfa) and sfa > cfg["single_feature_auc_max"]:
        reasons.append(f"single-feature AUC {sfa:.3f} > {cfg['single_feature_auc_max']}")
    name_hit = any(re.search(p, col, re.I) for p in cfg.get("target_like_name_patterns", []))
    if name_hit:
        reasons.append("target-like column name")
    derived = bool(source_tables and set(t.lower() for t in source_tables) & TARGET_SOURCE_TABLES)
    if derived:
        reasons.append("derived from performance/label tables")
    avail = (lineage or {}).get("available_at")
    hard = bool(
        (share is not None and share > cfg["post_decision_share_max"])
        or derived
        or (sfa is not None and not np.isnan(sfa) and sfa > cfg["single_feature_auc_max"])
    )
    if hard:
        risk = "high"
    elif name_hit or avail in ("unknown", "post_decision"):
        risk = "medium"
        if avail in ("unknown", "post_decision"):
            reasons.append(f"lineage availability '{avail}'")
    else:
        risk = "low"
    return LeakageFinding(col, share, None if sfa is None else float(sfa), name_hit, avail, derived, risk, reasons)


def check_features(
    df: pd.DataFrame,
    features: list[str],
    y: np.ndarray | None,
    cfg: dict,
    lineage: dict[str, dict] | None = None,
    source_tables: dict[str, list[str]] | None = None,
) -> list[LeakageFinding]:
    lineage = lineage or {}
    source_tables = source_tables or {}
    return [check_column(df, f, y, cfg, lineage.get(f), source_tables.get(f)) for f in features if f in df]
