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

from lau.console import deps
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
def evidence(candidate_ref: str) -> dict:
    packet = approvals.evidence_packet(_ref(candidate_ref))
    if packet is None:
        raise HTTPException(status_code=404, detail="no evaluation for this candidate")
    return packet


@router.post("/approvals/{candidate_ref}/gate", dependencies=[Depends(deps.require_actions)])
def run_gate(candidate_ref: str) -> dict:
    ref = _ref(candidate_ref)
    packet = approvals.evidence_packet(ref)
    if packet is None:
        raise HTTPException(status_code=404, detail="no evaluation for this candidate")
    if not packet["can_run_gate"]:
        return {"ok": False, "message": "The gate cannot run: " + " ".join(packet["blockers"]), "ref": ref}
    from lau.harness.gate import promotion_gate
    from lau.modeling import registry_io

    mv = approvals.model_version_of(ref)
    model = registry_io.load_pd_model(registry_io.candidate_uri(mv), "harness")
    result = promotion_gate(model, packet["definition_version"], ref)
    clear_cache()
    passed = bool(result.get("passed"))
    failed = [k for k, v in (result.get("checks") or {}).items() if not v]
    message = (
        f"Holdout gate passed (holdout AUC {result['holdout']['auc']:.4f}). A person can now approve or reject."
        if passed
        else f"Holdout gate failed: {', '.join(failed) or 'see the checks'}. Nothing can be promoted."
    )
    return {"ok": passed, "message": message, "ref": str(result.get("gate_id"))}


@router.post("/approvals/{candidate_ref}/decision", dependencies=[Depends(deps.require_actions)])
def decide(candidate_ref: str, request: Request, body: dict = Body(...)) -> dict:
    from lau.promotion.promote import record_approval

    ref = _ref(candidate_ref)
    try:
        decision, rationale = approvals.decision_payload(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    packet = approvals.evidence_packet(ref)
    if packet is None:
        raise HTTPException(status_code=404, detail="no evaluation for this candidate")
    if not packet["can_decide"]:
        return {
            "ok": False,
            "message": "No decision can be recorded: "
            + " ".join(packet["blockers"] or ["a passing holdout gate without a decision is required."]),
            "ref": ref,
        }
    gate = approvals.gate_id_for(ref)
    assert gate is not None  # can_decide implies a passing gate
    approval_id = record_approval(ref, decision, rationale, gate[0], gate[1], approver=deps.current_user(request))
    clear_cache()
    verb = "Approved" if decision == "approve" else "Rejected"
    nxt = " It can now be promoted." if decision == "approve" else ""
    return {"ok": True, "message": f"{verb} and recorded as {approval_id}.{nxt}", "ref": approval_id}


@router.post("/approvals/{candidate_ref}/promote", dependencies=[Depends(deps.require_actions)])
def promote(candidate_ref: str) -> dict:
    from lau.promotion.promote import PromotionBlockedError
    from lau.promotion.promote import promote as do_promote

    ref = _ref(candidate_ref)
    packet = approvals.evidence_packet(ref)
    if packet is None:
        raise HTTPException(status_code=404, detail="no evaluation for this candidate")
    if not packet["can_promote"]:
        return {
            "ok": False,
            "message": "Not promotable: "
            + " ".join(packet["blockers"] or ["an approval of the latest passing gate is required."]),
            "ref": ref,
        }
    try:
        promo = do_promote(approvals.model_version_of(ref), log=lambda _m: None)
    except PromotionBlockedError as e:
        return {"ok": False, "message": f"Promotion blocked: {e}", "ref": ref}
    clear_cache()
    serving = " It is now serving." if promo.get("serving") else " It is champion for its definition but not serving."
    return {
        "ok": True,
        "message": f"Promoted to production v{promo['production_model_version']}.{serving}",
        "ref": str(promo["promotion_id"]),
    }
