"""Console API (screens 16-18, operate):
- GET /api/rollouts                 promotions; staged rollouts are Unavailable until the decision API exists
- GET /api/shadow                   shadow-scoring aggregates
- GET /api/alerts                   monitoring alerts and runs
- POST /api/alerts/{alert_id}/ack   {note}; appends to ops.alert_acks as the harness identity

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import Body, Depends, HTTPException, Request

from lau.console import actions, deps
from lau.console.services import models, ops
from lau.console.util import api_router, boolean, clear_cache, iso, safe_token, text, unavailable

router = api_router()


@router.get("/rollouts")
def rollouts() -> dict:
    df = models.promotions()
    return {
        "live": unavailable(
            "Staged rollouts (canary share, automatic rollback) need the real-time decision API. Today a promotion "
            "moves the serving alias in one step, and rollback means promoting the previous champion again.",
            ["Real-time decision API (Model Serving) with traffic splitting", "Decision log for rollout monitoring"],
        ),
        "promotions": [
            {
                "promotion_id": str(r["promotion_id"]),
                "ts": iso(r["ts"]),
                "definition_version": str(r["definition_version"]),
                "production_model_version": str(r["production_model_version"]),
                "candidate_model_version": str(r["candidate_model_version"]),
                "previous_champion_version": text(r.get("previous_champion_version")),
                "serving": bool(boolean(r.get("serving"))),
                "approval_id": str(r.get("approval_id") or ""),
            }
            for r in df.to_dict("records")
        ]
        if len(df)
        else [],
    }


@router.get("/shadow")
def shadow() -> dict:
    return ops.shadow()


@router.get("/alerts")
def alerts() -> dict:
    items = ops.alerts()
    runs = ops.monitoring_runs()
    if not items and not runs:
        return {
            "available": False,
            "reason": "Monitoring has not run yet (lau monitor, or the lau-monitoring job).",
            "alerts": [],
            "monitoring_runs": [],
        }
    return {
        "available": True,
        "reason": None,
        "alerts": items,
        "monitoring_runs": [{k: v for k, v in r.items() if k != "summary"} for r in runs],
    }


@router.post("/alerts/{alert_id}/ack", dependencies=[Depends(deps.require_actions)])
def acknowledge(alert_id: str, request: Request, body: dict = Body(default={})) -> dict:
    if not safe_token(alert_id):
        raise HTTPException(status_code=400, detail="invalid alert id")
    if alert_id not in {a["id"] for a in ops.alerts()}:
        raise HTTPException(status_code=404, detail="unknown alert")
    result = actions.dispatch("ack", alert_id=alert_id, note=str(body.get("note") or ""), by=deps.current_user(request))
    clear_cache()
    return result
