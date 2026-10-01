"""Console API (screen 15, approvals):
- GET /api/approvals, GET /api/approvals/{candidate_ref}
- POST /api/approvals/{candidate_ref}/gate       run the holdout promotion gate (uses the holdout budget)
- POST /api/approvals/{candidate_ref}/decision   {decision: approve|reject, rationale}
- POST /api/approvals/{candidate_ref}/promote    promote an approved candidate (promoter identity)

Actions are off unless LAU_CONSOLE_ACTIONS=1. They call the same code paths as the CLI (`lau promote`): the harness
identity runs the gate, the approval is recorded with the requesting user, and only the promoter identity writes
production. The console's own read identity never writes.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import Body, Depends, HTTPException, Request

from lau.console import actions, deps
from lau.console.services import approvals, evals
from lau.console.util import api_router, clear_cache, safe_token

router = api_router()


def _ref(candidate_ref: str) -> str:
    if not safe_token(candidate_ref):
        raise HTTPException(status_code=400, detail="invalid candidate ref")
    return candidate_ref


@router.get("/approvals")
def approvals_list() -> dict:
    return {
        "pending": approvals.waiting_items(),
        "history": evals.approval_history(),
        "actions_enabled": deps.actions_enabled(),
    }


@router.get("/approvals/{candidate_ref}")
def evidence(candidate_ref: str, request: Request) -> dict:
    packet = approvals.evidence_packet(_ref(candidate_ref), user=deps.current_user(request))
    if packet is None:
        raise HTTPException(status_code=404, detail="no evaluation for this candidate")
    return packet


def _packet_or_404(ref: str, request: Request) -> dict:
    packet = approvals.evidence_packet(ref, user=deps.current_user(request))
    if packet is None:
        raise HTTPException(status_code=404, detail="no evaluation for this candidate")
    return packet


def _blocked(prefix: str, packet: dict, fallback: str, ref: str) -> dict:
    return {"ok": False, "message": f"{prefix}: " + " ".join(packet["blockers"] or [fallback]), "ref": ref}


@router.post("/approvals/{candidate_ref}/gate", dependencies=[Depends(deps.require_actions)])
def run_gate(candidate_ref: str, request: Request) -> dict:
    ref = _ref(candidate_ref)
    packet = _packet_or_404(ref, request)
    if not packet["can_run_gate"]:
        return _blocked("The gate cannot run", packet, "it is not ready for the holdout gate.", ref)
    result = actions.dispatch("gate", candidate_ref=ref)
    clear_cache()
    return result


@router.post("/approvals/{candidate_ref}/decision", dependencies=[Depends(deps.require_actions)])
def decide(candidate_ref: str, request: Request, body: dict = Body(...)) -> dict:
    ref = _ref(candidate_ref)
    try:
        decision, rationale = approvals.decision_payload(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    packet = _packet_or_404(ref, request)
    if not packet["can_decide"]:
        return _blocked("No decision can be recorded", packet, "a passing holdout gate is required.", ref)
    result = actions.dispatch(
        "decide", candidate_ref=ref, decision=decision, rationale=rationale, approver=deps.current_user(request)
    )
    clear_cache()
    return result


@router.post("/approvals/{candidate_ref}/promote", dependencies=[Depends(deps.require_actions)])
def promote(candidate_ref: str, request: Request) -> dict:
    ref = _ref(candidate_ref)
    packet = _packet_or_404(ref, request)
    if not packet["can_promote"]:
        return _blocked("Not promotable", packet, "the required approvals of the latest passing gate are missing.", ref)
    result = actions.dispatch("promote", candidate_ref=ref)
    clear_cache()
    return result
