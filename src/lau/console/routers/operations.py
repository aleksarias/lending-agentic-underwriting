"""Console API (screens 16-18, operate):
- GET /api/rollouts                 shadow-first rollouts (state, events, approvals, shadow report) and promotions
- POST /api/rollouts/{id}/decide    {decision: approve|reject, note}; two-person rule (approvals.rollout)
- POST /api/rollouts/{id}/serve     the approved champion starts deciding (promoter identity)
- POST /api/rollouts/{id}/rollback  {reason}; serving returns to the previous model or the legacy policy
- GET /api/shadow                   shadow-scoring aggregates
- GET /api/alerts                   monitoring alerts and runs
- POST /api/alerts/{alert_id}/ack   {note}; appends to ops.alert_acks as the harness identity

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import Body, Depends, HTTPException, Request

from lau.console import actions, deps
from lau.console.services import models, ops
from lau.console.util import api_router, boolean, clear_cache, iso, safe_token, text

router = api_router()


@router.get("/rollouts")
def rollouts() -> dict:
    from lau.console.services import decisions

    df = models.promotions()
    view = decisions.rollouts_view()
    return {
        "available": True,
        "reason": None
        if view["rollouts"]
        else "No champion has been promoted since rollouts started: a promotion starts one in shadow.",
        **view,
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


def _rollout_or_404(rollout_id: str) -> None:
    from lau.console.services import decisions

    if not safe_token(rollout_id):
        raise HTTPException(status_code=400, detail="invalid rollout id")
    if rollout_id not in {r["rollout_id"] for r in decisions.rollouts_list()}:
        raise HTTPException(status_code=404, detail="unknown rollout")


@router.post("/rollouts/{rollout_id}/decide", dependencies=[Depends(deps.require_actions)])
def rollout_decide(rollout_id: str, request: Request, body: dict = Body(default={})) -> dict:
    _rollout_or_404(rollout_id)
    decision = str(body.get("decision") or "")
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be approve or reject")
    result = actions.dispatch(
        "rollout_decide",
        rollout_id=rollout_id,
        decision=decision,
        note=str(body.get("note") or ""),
        approver=deps.current_user(request),
    )
    clear_cache()
    return result


@router.post("/rollouts/{rollout_id}/serve", dependencies=[Depends(deps.require_actions)])
def rollout_serve(rollout_id: str, request: Request) -> dict:
    _rollout_or_404(rollout_id)
    result = actions.dispatch("rollout_serve", rollout_id=rollout_id, by=deps.current_user(request))
    clear_cache()
    return result


@router.post("/rollouts/{rollout_id}/rollback", dependencies=[Depends(deps.require_actions)])
def rollout_rollback(rollout_id: str, request: Request, body: dict = Body(default={})) -> dict:
    _rollout_or_404(rollout_id)
    reason = str(body.get("reason") or "").strip()
    if len(reason) < 10:
        raise HTTPException(status_code=400, detail="a rollback needs a reason of at least 10 characters")
    result = actions.dispatch("rollout_rollback", rollout_id=rollout_id, reason=reason, by=deps.current_user(request))
    clear_cache()
    return result


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
