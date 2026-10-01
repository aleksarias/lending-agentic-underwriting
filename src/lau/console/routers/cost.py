"""Console API: GET /api/cost (screen 19).

Spend is what the system logged (ops.cost_log: Anthropic ResultMessage costs and metered warehouse time priced at
the configured $/DBU). Actual Databricks billing (system.billing) is not readable by the console identity.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from lau.console.services import config, ops
from lau.console.util import api_router
from lau.settings import get_settings

router = api_router()


@router.get("/cost")
def cost() -> dict:
    df = ops.cost_log()
    by_day: dict[str, dict] = {}
    by_cycle: dict[str, dict] = {}
    for r in df.to_dict("records") if len(df) else []:
        usd = float(r.get("usd") or 0.0)
        bucket = "anthropic" if str(r.get("kind")) == "anthropic" else "databricks"
        day = r["ts"].strftime("%Y-%m-%d")
        by_day.setdefault(day, {"day": day, "anthropic": 0.0, "databricks": 0.0})[bucket] += usd
        cid = str(r.get("cycle_id") or "")
        if cid:
            by_cycle.setdefault(cid, {"cycle_id": cid, "anthropic": 0.0, "databricks": 0.0})[bucket] += usd
    runs = ops.agent_runs()
    live = ops.running_cycle()
    if live is not None and len(runs):  # a running cycle logs its cost when it ends; count its runs then too
        runs = runs[runs["cycle_id"] != live["cycle_id"]]
    by_agent = []
    if len(runs):
        costed = runs[runs["cost_usd"].fillna(0) > 0]
        for agent, g in costed.groupby("agent"):
            by_agent.append({"agent": str(agent), "cost_usd": round(float(g["cost_usd"].sum()), 4), "runs": len(g)})
        by_agent.sort(key=lambda a: a["cost_usd"], reverse=True)
    caps = config.cycle_caps()
    wh = get_settings().project.warehouse

    def rounded(d: dict) -> dict:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()}

    return {
        "month_to_date_usd": round(ops.month_to_date_usd(), 4),
        "hard_stop_usd": ops.hard_stop_usd(),
        "cycle_caps": {
            "anthropic_usd": float(caps.get("max_anthropic_usd", 0.0)),
            "dbu": float(caps.get("max_databricks_dbu", 0.0)),
        },
        "by_day": [rounded(v) for _, v in sorted(by_day.items())],
        "by_cycle": [rounded(v) for _, v in sorted(by_cycle.items(), reverse=True)],
        "by_agent": by_agent,
        "pricing": {
            "usd_per_dbu": float(getattr(wh, "usd_per_dbu", 0.0)),
            "dbu_per_hour": float(getattr(wh, "dbu_per_hour", 0.0)),
            "warehouse_size": str(getattr(wh, "cluster_size", "")),
        },
        "billing_available": False,
    }
