"""Console API: GET /api/upcoming (screen 7: what the system will do next).

Jobs are the schedules declared in the Databricks Asset Bundle (deployed paused); the queue, plan, budget forecast
and backlog come from ops tables and the latest planner output.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

import calendar

import pandas as pd

from lau.console import deps
from lau.console.services import approvals, evals, ledger, ops
from lau.console.services import definitions as defs
from lau.console.util import api_router, now_utc, read_table, text

router = api_router()


def _month_end_usd() -> float | None:
    mtd = ops.month_to_date_usd()
    now = now_utc()
    days = calendar.monthrange(now.year, now.month)[1]
    return round(mtd / max(now.day, 1) * days, 2) if mtd else None


def _maturation(version: str | None) -> dict | None:
    """When the next origination month gains a full observation window of performance."""
    ref = defs.definition_ref(version)
    data = ops.latest_data_version()
    if not ref or not data or not text(data.get("as_of_month")):
        return None
    as_of = pd.Period(str(data["as_of_month"]), "M")
    newest_mature = as_of - ref["window_months"]
    return {
        "definition_version": str(version),
        "months_until_next_window": 1,
        "note": (
            f"Performance runs through {as_of}. Loans originated through {newest_mature} have the full "
            f"{ref['window_months']}-month window; each new month of performance matures one more origination month."
        ),
    }


def _backlog(plan: dict | None, plan_cycle: str | None) -> list[dict]:
    items: list[dict] = []
    for key in ("next_hypotheses", "hypotheses", "backlog", "goals"):
        for h in (plan or {}).get(key) or []:
            textual = h if isinstance(h, str) else (h.get("hypothesis") or h.get("goal") or h.get("text"))
            if textual:
                items.append({"hypothesis": str(textual)[:400], "source": f"planner ({plan_cycle})"})
    feats = read_table(
        deps.ui_store(),
        "feature_registry",
        "features",
        columns=["name", "hypothesis", "status", "cycle_id"],
        where="status = 'proposed'",
        limit=50,
    )
    for r in feats.to_dict("records") if len(feats) else []:
        if text(r.get("hypothesis")):
            items.append(
                {"hypothesis": f"{r['name']}: {r['hypothesis']}"[:400], "source": f"feature proposal ({r['cycle_id']})"}
            )
    return items[:40]


@router.get("/upcoming")
def upcoming() -> dict:
    active = defs.active_version()
    den = (ledger.latest() or {}).get("denominator") or {}
    used, budget = evals.holdout_used(active), evals.holdout_budget()
    plan_cycle, plan = ops.latest_plan()
    return {
        "jobs": ops.declared_jobs(),
        "queue": ops.queue(),
        "next_plan": plan,
        "waiting": approvals.waiting_items(),
        "forecast": {
            "month_end_usd": _month_end_usd(),
            "tests_since_reset": int(den.get("tests_since_reset") or 0),
            "next_margin": float(den.get("next_margin") or 0.0),
            "holdout_remaining": max(0, budget - used),
            "maturation": _maturation(active),
        },
        "backlog": _backlog(plan, plan_cycle),
    }
