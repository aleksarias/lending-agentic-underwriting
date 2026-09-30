"""Console API (screen 6, definitions over time):
- GET /api/definitions, GET /api/definitions/sensitivity, GET /api/definitions/{version}
- GET /api/pipeline?[def]

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import HTTPException

from lau.console.services import definitions as defs
from lau.console.services import ops
from lau.console.util import DEF_PARAM, api_router

router = api_router()


@router.get("/definitions")
def definitions() -> list[dict]:
    return defs.all_definition_payloads()


# Declared before /definitions/{version} so "sensitivity" is never read as a version.
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
    v = defs.resolve_version(version) if version else defs.active_version()
    return {"definition_version": v, "stages": ops.freshness(v), "runs": ops.pipeline_runs(v)}
