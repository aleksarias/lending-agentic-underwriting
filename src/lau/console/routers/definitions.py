"""Console API (screen 6, definitions over time):
- GET /api/definitions, GET /api/definitions/sensitivity, GET /api/definitions/{version}
- GET /api/definitions/proposal          the YAML definition when it differs from the active one
- POST /api/definitions/{version}/approve {note}: approve that exact hash (two-person rule; actions only)
- GET /api/pipeline?[def]

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import Body, Depends, HTTPException, Request

from lau.console import deps
from lau.console.services import definitions as defs
from lau.console.services import ops
from lau.console.util import DEF_PARAM, api_router, safe_token

router = api_router()


@router.get("/definitions")
def definitions() -> list[dict]:
    return defs.all_definition_payloads()


# Declared before /definitions/{version} so "sensitivity" is never read as a version.
@router.get("/definitions/proposal")
def proposal() -> dict:
    """The YAML definition when it differs from the active one (or {"proposal": null})."""
    return {"proposal": defs.proposal()}


@router.post("/definitions/{version}/approve", dependencies=[Depends(deps.require_actions)])
def approve(version: str, request: Request, body: dict = Body(default={})) -> dict:
    from lau.console import actions
    from lau.console.util import clear_cache

    if not safe_token(version):
        raise HTTPException(status_code=400, detail="invalid version")
    result = actions.dispatch(
        "definition_approve", version=version, note=str(body.get("note") or ""), approver=deps.current_user(request)
    )
    clear_cache()
    return result


@router.get("/definitions/sensitivity")
def sensitivity() -> dict:
    return defs.sensitivity()


@router.get("/definitions/{version}")
def definition(version: str) -> dict:
    resolved = defs.resolve_version(version)
    payload = defs.definition_version_payload(resolved) if resolved else None
    if payload is None:
        raise HTTPException(status_code=404, detail="unknown definition version")
    return payload


@router.get("/pipeline")
def pipeline(version: str | None = DEF_PARAM) -> dict:
    v = defs.resolve_or_404(version) or None
    return {"definition_version": v, "stages": ops.freshness(v), "runs": ops.pipeline_runs(v)}
