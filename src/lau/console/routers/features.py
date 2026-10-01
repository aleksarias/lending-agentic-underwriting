"""Console API (screen 13, features lab):
- GET /api/features                      proposals, measured performance, usage, and a person's rejection if any
- POST /api/features/{name}/decision     {decision: reject|restore, reason}; the harness enforces rejections
- GET /api/hypotheses                    hypotheses people pinned for the next plans
- POST /api/hypotheses {text}            pin one;  POST /api/hypotheses/{id}/unpin

Feature proposals are agent output (feature_registry.features); their measured performance per definition comes
from the pipeline's re-evaluation (feature_registry.feature_performance); usage from harness evaluations.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import Body, Depends, HTTPException, Request

from lau.console import actions, deps
from lau.console.services import models
from lau.console.util import api_router, clear_cache, iso, loads, num, read_table, safe_token, text, ttl_cache

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
    rejected = _rejected()
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
            "rejected": rejected.get(str(r["name"])),
        }
        for r in df.sort_values("created_at", ascending=False).to_dict("records")
    ]


def _rejected() -> dict[str, dict]:
    from lau.governance.human_input import rejected_features

    try:
        found = rejected_features(deps.ui_store())
    except Exception:  # noqa: BLE001 - not visible yet
        return {}
    return {k: {"reason": v["reason"], "by": v["by_user"], "at": iso(v["ts"])} for k, v in found.items()}


@router.post("/features/{name}/decision", dependencies=[Depends(deps.require_actions)])
def feature_decision(name: str, request: Request, body: dict = Body(default={})) -> dict:
    if not safe_token(name):
        raise HTTPException(status_code=400, detail="invalid feature name")
    decision = str(body.get("decision") or "")
    if decision not in ("reject", "restore"):
        raise HTTPException(status_code=400, detail="decision must be reject or restore")
    result = actions.dispatch(
        "feature_decision",
        name=name,
        decision=decision,
        reason=str(body.get("reason") or ""),
        by=deps.current_user(request),
    )
    clear_cache()
    return result


@router.get("/hypotheses")
def hypotheses() -> list[dict]:
    from lau.governance.human_input import pinned

    try:
        rows = pinned(deps.ui_store())
    except Exception:  # noqa: BLE001 - none yet
        return []
    return [
        {"hypothesis_id": h["hypothesis_id"], "text": h["text"], "by": h["by_user"], "at": iso(h["ts"])} for h in rows
    ]


@router.post("/hypotheses", dependencies=[Depends(deps.require_actions)])
def pin_hypothesis(request: Request, body: dict = Body(default={})) -> dict:
    result = actions.dispatch("hypothesis_pin", text=str(body.get("text") or ""), by=deps.current_user(request))
    clear_cache()
    return result


@router.post("/hypotheses/{hypothesis_id}/unpin", dependencies=[Depends(deps.require_actions)])
def unpin_hypothesis(hypothesis_id: str, request: Request) -> dict:
    if not safe_token(hypothesis_id):
        raise HTTPException(status_code=400, detail="invalid id")
    result = actions.dispatch("hypothesis_unpin", hypothesis_id=hypothesis_id, by=deps.current_user(request))
    clear_cache()
    return result
