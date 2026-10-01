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


def _backlog(active: str | None) -> list[dict]:
    """Open research questions: proposed features no model has used yet, and lessons carried over from an earlier
    definition that have not been re-verified under the active one. (The latest plan already ran; it is shown as
    the plan, not as backlog.)"""
    from lau.agents.lessons import read_lessons
    from lau.console.routers.features import _usage

    items: list[dict] = []
    used = set(_usage())
    feats = read_table(
        deps.ui_store(),
        "feature_registry",
        "features",
        columns=["name", "hypothesis", "status", "cycle_id", "created_at"],
        ts=["created_at"],
    )
    if len(feats):
        feats = feats.sort_values("created_at", ascending=False).drop_duplicates("name")
        for r in feats.to_dict("records"):
            if r["name"] in used or str(r.get("status")) not in ("proposed", "screened", "accepted"):
                continue
            hypothesis = text(r.get("hypothesis")) or "no hypothesis recorded"
            items.append(
                {
                    "hypothesis": f"{r['name']}: {hypothesis}"[:400],  # "name: hypothesis" (the page links the name)
                    "source": f"feature proposal ({r['cycle_id']})",
                }
            )
    if active:
        pending = f"unverified-under-{active[:8]}"
        for lesson in read_lessons():
            if lesson.status == pending:
                items.append(
                    {
                        "hypothesis": f"Re-verify under the active definition: {lesson.text}"[:400],
                        "source": f"lesson {lesson.id}",
                    }
                )
    return items[:60]


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
        "next_plan_cycle_id": plan_cycle,
        "waiting": approvals.waiting_items(),
        "forecast": {
            "month_end_usd": _month_end_usd(),
            "tests_since_reset": int(den.get("tests_since_reset") or 0),
            "next_margin": float(den.get("next_margin") or 0.0),
            "holdout_remaining": max(0, budget - used),
            "maturation": _maturation(active),
        },
        "backlog": _backlog(active),
    }
