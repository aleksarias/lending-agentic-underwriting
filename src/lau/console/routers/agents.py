"""Console API (screen 14, agents):
- GET /api/agents
- GET /api/reports?[kind]&[cycle_id]&[candidate_ref], GET /api/reports/{report_id}
- GET /api/lessons

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from functools import lru_cache
from types import SimpleNamespace

from fastapi import HTTPException

from lau.console import deps
from lau.console.services import config, ops, reports
from lau.console.services import definitions as defs
from lau.console.util import api_router, query, safe_token, table_exists, ttl_cache

router = api_router()


@lru_cache(maxsize=1)
def _role_tools() -> dict[str, list[str]]:
    """Tool names each role is allowed, built from the real tool factories (construction has no side effects)."""
    from lau.agents.tools import role_tools as rt

    ctx = SimpleNamespace(cycle_id="console", version="", trace=None, budgets={}, experiments_used=0)
    out: dict[str, list[str]] = {}
    for role in ops.AGENT_ROLES:
        fn = getattr(rt, f"{role}_tools", None)
        try:
            tools = fn(ctx, lambda: {}) if role == "planner" else fn(ctx)  # type: ignore[misc]
        except Exception:  # noqa: BLE001 - show the role even if a factory changes signature
            tools = []
        out[role] = [str(getattr(t, "name", t)) for t in tools]
    return out


@ttl_cache(60)
def _prompt_hashes() -> dict[str, str]:
    from lau.versioning import current_versions

    try:
        return {k.split(":", 1)[1]: v[0] for k, v in current_versions().items() if k.startswith("prompt:")}
    except Exception:  # noqa: BLE001
        return {}


@router.get("/agents")
def agents() -> list[dict]:
    runs = ops.agent_runs()
    tools = _role_tools()
    hashes = _prompt_hashes()
    calls_by_role = _tool_calls()
    out = []
    for role in ops.AGENT_ROLES:
        mine = runs[runs["agent"] == role] if len(runs) else runs
        # the post-run trace flush repeats a run with zero cost; count costed runs only when both exist
        costed = mine[mine["cost_usd"].fillna(0) > 0] if len(mine) else mine
        counted = costed if len(costed) else mine
        n_calls, n_errors = calls_by_role.get(role, (0, 0))
        tool_error_rate = n_errors / n_calls if n_calls else None
        out.append(
            {
                "role": role,
                "model": str(config.model_config().get("agents", {}).get(role, "")),
                "caps": config.agent_caps(role),
                "prompt_hash": hashes.get(role, ""),
                "tools": tools.get(role, []),
                "runs": len(counted),
                "total_cost_usd": round(float(counted["cost_usd"].fillna(0).sum()), 4) if len(counted) else 0.0,
                "avg_turns": float(counted["turns"].mean()) if len(counted) else None,
                "tool_error_rate": tool_error_rate,
            }
        )
    return out


@ttl_cache(30)
def _tool_calls() -> dict[str, tuple[int, int]]:
    """{role: (tool calls, errored tool calls)} over the whole trace (agent_run rows excluded)."""
    st = deps.ui_store()
    if not table_exists(st, "ops", "agent_trace"):
        return {}
    df = query(
        st,
        f"SELECT agent, count(*) AS n, sum(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors "
        f"FROM {st.fq('ops', 'agent_trace')} WHERE action NOT IN ('agent_run', 'denied_tool') GROUP BY agent",
    )
    return {str(r["agent"]): (int(r["n"]), int(r["errors"] or 0)) for r in df.to_dict("records")}


@router.get("/reports")
def report_list(kind: str | None = None, cycle_id: str | None = None, candidate_ref: str | None = None) -> list[dict]:
    return reports.list_meta(kind=kind or None, cycle_id=cycle_id or None, candidate_ref=candidate_ref or None)


@router.get("/reports/{report_id}")
def report(report_id: str) -> dict:
    if not safe_token(report_id):
        raise HTTPException(status_code=400, detail="invalid report id")
    r = reports.report_with_body(report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="unknown report")
    return r


@router.get("/lessons")
def lessons() -> dict:
    """Lessons from ops.lessons (Databricks, or the mirror of it), else the local LESSONS.md."""
    from lau.agents.lessons import _read_file

    st = deps.ui_store()
    if table_exists(st, "ops", "lessons"):
        df = query(
            st, f"SELECT id, definition_version, scope, status, text FROM {st.fq('ops', 'lessons')} ORDER BY ord"
        )
        rows = df.to_dict("records")
    else:
        rows = [x.__dict__ for x in _read_file()]
    return {
        "active_definition": defs.active_version(),
        "lessons": [
            {
                "id": str(x["id"]),
                "definition_version": str(x["definition_version"]),
                "scope": str(x["scope"]),
                "status": str(x["status"]),
                "text": str(x["text"]),
            }
            for x in rows
        ],
    }
