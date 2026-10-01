"""Console API: GET /api/fairness?[def] (screen 10, fairness and compliance).

Adverse impact ratios come from harness evaluations; the proxy heat map from ops.proxy_scan (aggregates only, no
row-level protected attributes); findings are the compliance agent's reports (agent claims, shown as such).

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

import pandas as pd

from lau.console import deps
from lau.console.services import config, reports
from lau.console.services import definitions as defs
from lau.console.util import DEF_PARAM, api_router, boolean, iso, loads, num, read_table, sql_str, table_exists, text

router = api_router()
MAX_HEATMAP_FEATURES = 40


def _classes(fair: dict) -> dict:
    return {
        str(name): {
            "reference_group": str(c.get("reference_group", "")),
            "approval_rates": {str(k): num(v) for k, v in (c.get("approval_rates") or {}).items()},
            "air": {str(k): num(v) for k, v in (c.get("air") or {}).items()},
            "min_air": num(c.get("min_air")),
        }
        for name, c in (fair.get("classes") or {}).items()
    }


def _candidates(version: str) -> list[dict]:
    df = read_table(
        deps.ui_store(),
        "ops",
        "evaluations",
        columns=["eval_id", "candidate_ref", "ts", "result_json"],
        where=f"definition_version = {sql_str(version)}",
        order_by="ts DESC",
        limit=100,
        ts=["ts"],
    )
    out = []
    for r in df.to_dict("records") if len(df) else []:
        fair = (loads(r.get("result_json"), {}) or {}).get("fairness") or {}
        out.append(
            {
                "candidate_ref": str(r["candidate_ref"]),
                "eval_id": str(r["eval_id"]),
                "ts": iso(r["ts"]),
                "min_air": num(fair.get("min_air")),
                "classes": _classes(fair),
            }
        )
    return out


def _proxy_heatmap(version: str) -> list[dict]:
    st = deps.ui_store()
    if not table_exists(st, "ops", "proxy_scan"):
        return []
    t = st.fq("ops", "proxy_scan")
    df = read_table(
        st,
        "ops",
        "proxy_scan",
        where=f"run_id = (SELECT run_id FROM {t} ORDER BY computed_at DESC LIMIT 1)",
        columns=["definition_version", "feature", "protected_class", "protected_group", "proxy_auc", "flagged"],
    )
    if df.empty:
        return []
    if (df["definition_version"] == version).any():
        df = df[df["definition_version"] == version]
    top = df.groupby("feature")["proxy_auc"].max().sort_values(ascending=False).head(MAX_HEATMAP_FEATURES).index
    flagged = set(df.loc[df["flagged"].fillna(False).astype(bool), "feature"])
    keep = set(top) | flagged
    df = df[df["feature"].isin(keep)]
    order = {f: i for i, f in enumerate(df.groupby("feature")["proxy_auc"].max().sort_values(ascending=False).index)}
    df = df.assign(_o=df["feature"].map(order)).sort_values(["_o", "protected_class", "protected_group"])
    return [
        {
            "feature": str(r["feature"]),
            "protected_class": str(r["protected_class"]),
            "protected_group": None
            if text(r.get("protected_group")) in (None, "pooled")
            else str(r["protected_group"]),
            "proxy_auc": num(r["proxy_auc"]) or 0.0,
            "flagged": bool(boolean(r.get("flagged"))),
        }
        for r in df.to_dict("records")
        if not pd.isna(r["proxy_auc"])
    ]


@router.get("/fairness")
def fairness(version: str | None = DEF_PARAM) -> dict:
    v = defs.resolve_or_404(version)
    th = config.thresholds().get("fairness", {})
    prot = config.protected()
    findings = [m for m in reports.list_meta(kind="compliance") if m["definition_version"] in ("", v)]
    return {
        "definition_version": v,
        "threshold_air": float(th.get("min_air", 0.8)),
        "approval_rate": float(th.get("approval_rate", config.fixed_approval_rate())),
        "candidates": _candidates(v) if v else [],
        "proxy_heatmap": _proxy_heatmap(v),
        "proxy_threshold": float(th.get("proxy_auc_flag", 0.65)),
        "prohibited_features": [str(x) for x in prot.get("prohibited_features") or []],
        "findings": findings,
    }
