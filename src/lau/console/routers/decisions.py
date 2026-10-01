"""Console API (screen 3, decisions):
- GET /api/decisions                              last 30 days of decisions, the active policy, the decision API state
- GET /api/decisions/search?q=                     by decision id or application id prefix
- GET /api/decisions/{decision_id}                 one decision: reasons, versions, shadow score, latency
- GET /api/decisions/{decision_id}/adverse-action  principal reasons as an applicant reads them (counsel approves
                                                   the notice itself)
Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import HTTPException, Query

from lau.console.services import decisions as svc
from lau.console.util import api_router, safe_token

router = api_router()


@router.get("/decisions")
def decisions() -> dict:
    return svc.overview()


@router.get("/decisions/search")
def search(q: str = Query("", max_length=64)) -> dict:
    if q and not safe_token(q):
        raise HTTPException(status_code=400, detail="invalid search")
    return {"results": svc.search(q)}


@router.get("/decisions/{decision_id}")
def decision(decision_id: str) -> dict:
    if not safe_token(decision_id):
        raise HTTPException(status_code=400, detail="invalid decision id")
    found = svc.detail(decision_id)
    if found is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    return found


@router.get("/decisions/{decision_id}/adverse-action")
def adverse_action(decision_id: str) -> dict:
    from lau.console import deps
    from lau.decision.notices import notice

    if not safe_token(decision_id):
        raise HTTPException(status_code=400, detail="invalid decision id")
    found = notice(decision_id, store=deps.ui_store()) if svc.available() else None
    if found is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    return {k: v for k, v in found.items() if k != "for_reviewers"}
