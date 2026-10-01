"""Console API: GET /api/activity, GET /api/activity/trace, POST /api/activity/stop (screen 2, live research).

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import Body, Depends, HTTPException, Request

from lau.console import actions, deps
from lau.console.services import definitions as defs
from lau.console.services import ops
from lau.console.util import api_router, clear_cache, iso, safe_token

router = api_router()


@router.get("/activity")
def activity() -> dict:
    run = ops.running_cycle()
    live = None
    if run is not None:
        cid = str(run["cycle_id"])
        beat = ops.last_heartbeat(cid) or {}
        stopping = not ops.stop_requests(cid).empty
        live = {
            "cycle_id": cid,
            "definition_version": str(run["definition_version"]),
            "reason": str(run.get("reason") or ""),
            "started_at": iso(run["started_at"]),
            "state": "stopping" if stopping else "running",
            "current_step": beat.get("step"),
            "heartbeat_at": iso(beat.get("ts")),
            "lanes": ops.lanes(cid),
            "gauges": ops.gauges(cid, run["started_at"]),
            "trace": ops.trace_entries(cid, limit=200),
        }
    cycles = ops.cycles()
    last = None
    if len(cycles):
        done = cycles[cycles["cycle_id"] != (live or {}).get("cycle_id")]
        if len(done):
            last = ops.cycle_summary(done.iloc[0].to_dict())
    return {"cycle": live, "last_cycle": last, "pipeline": ops.freshness(defs.active_version())}


@router.get("/activity/trace")
def trace(cycle_id: str, after: str | None = None) -> list[dict]:
    if not safe_token(cycle_id):
        raise HTTPException(status_code=400, detail="invalid cycle id")
    return ops.trace_entries(cycle_id, after=after or None)


@router.post("/activity/stop", dependencies=[Depends(deps.require_actions)])
def stop(request: Request, body: dict = Body(...)) -> dict:
    cycle_id = str(body.get("cycle_id") or "")
    reason = str(body.get("reason") or "").strip()[:500]
    if not safe_token(cycle_id):
        raise HTTPException(status_code=400, detail="invalid cycle id")
    row = ops.cycle_row(cycle_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown cycle")
    if str(row.get("status")) != "running":
        return {"ok": False, "message": f"Cycle {cycle_id} is not running ({row.get('status')}).", "ref": cycle_id}
    user = deps.current_user(request)
    result = actions.dispatch("stop", cycle_id=cycle_id, reason=reason, by=user)
    clear_cache()
    return result
