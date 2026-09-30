"""Console API: GET /api/features (screen 13, features lab).

Feature proposals are agent output (feature_registry.features); their measured performance per definition comes
from the pipeline's re-evaluation (feature_registry.feature_performance); usage from harness evaluations.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from lau.console import deps
from lau.console.services import models
from lau.console.util import api_router, iso, loads, num, read_table, text, ttl_cache

router = api_router()


@ttl_cache(30)
def _usage() -> dict[str, list[str]]:
    """{engineered feature name: [model keys whose latest evaluation used it]}."""
    df = read_table(deps.ui_store(), "ops", "evaluations", columns=["candidate_ref", "ts", "result_json"], ts=["ts"])
    if df.empty:
        return {}
    df = df.sort_values("ts").groupby("candidate_ref").tail(1)
    out: dict[str, list[str]] = {}
    for r in df.to_dict("records"):
        m = (loads(r.get("result_json"), {}) or {}).get("model") or {}
        key = models.ref_for_candidate(str(r["candidate_ref"]))["key"]
        for name in m.get("engineered") or []:
            out.setdefault(str(name), []).append(key)
    return out


@router.get("/features")
def features() -> list[dict]:
    st = deps.ui_store()
    df = read_table(st, "feature_registry", "features", ts=["created_at"])
    if df.empty:
        return []
    perf = read_table(st, "feature_registry", "feature_performance", ts=["evaluated_at"])
    by_name: dict[str, dict] = {}
    if len(perf):
        perf = perf.sort_values("evaluated_at").groupby(["name", "definition_version"]).tail(1)
        for r in perf.to_dict("records"):
            by_name.setdefault(str(r["name"]), {})[str(r["definition_version"])] = {
                "auc": num(r.get("univariate_auc_train")),
                "missing_rate": num(r.get("missing_rate")),
                "leakage_risk": text(r.get("leakage_risk")),
                "proxy_risk": text(r.get("proxy_risk")),
            }
    usage = _usage()
    return [
        {
            "name": str(r["name"]),
            "expression": str(text(r.get("expression")) or ""),
            "rationale": str(text(r.get("rationale")) or ""),
            "hypothesis": str(text(r.get("hypothesis")) or ""),
            "author": str(text(r.get("author")) or ""),
            "cycle_id": str(text(r.get("cycle_id")) or ""),
            "created_at": iso(r["created_at"]),
            "created_under_definition": str(text(r.get("created_under_definition")) or ""),
            "status": str(text(r.get("status")) or ""),
            "performance": by_name.get(str(r["name"]), {}),
            "used_in": usage.get(str(r["name"]), []),
        }
        for r in df.sort_values("created_at", ascending=False).to_dict("records")
    ]
