"""Console API: GET /api/status (the status bar), GET /api/overview (screen 1).

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import Request

from lau.console import deps
from lau.console.services import approvals, config, evals, events, ledger, models, ops
from lau.console.services import definitions as defs
from lau.console.util import api_router, iso, now_utc, ttl_cache
from lau.settings import get_settings

router = api_router()

# Same wording as verdictLabel() in console/web/src/lib/format.ts
VERDICT_LABELS = {
    "improved": "Improved",
    "no_change": "No detectable change",
    "not_best": "Not the best available",
    "regressed": "Regressed",
    "insufficient_evidence": "Not enough evidence yet",
}


def _activity() -> dict:
    run = ops.running_cycle()
    if run is not None:
        beat = ops.last_heartbeat(str(run["cycle_id"])) or {}
        return {
            "state": "cycle_running",
            "cycle_id": str(run["cycle_id"]),
            "step": beat.get("step"),
            "since": iso(run["started_at"]),
        }
    pipe = ops.pipeline_running()
    if pipe is not None:
        return {"state": "pipeline_rebuilding", "cycle_id": None, "step": pipe["stage"], "since": pipe["since"]}
    return {"state": "idle", "cycle_id": None, "step": None, "since": None}


@ttl_cache(10)
def _status_core() -> dict:
    s = get_settings()
    active = defs.active_version()
    yaml_v = config.yaml_definition_version()
    serving = models.serving_model()
    latest_data = ops.latest_data_version()
    return {
        "generated_at": iso(now_utc()),
        "environment": "prod" if str(getattr(s.project, "environment", "dev")) == "prod" else "dev",
        "data_mode": "synthetic",
        "backend": "local" if s.project.backend == "local" else "databricks",
        "active_definition": defs.definition_ref(active),
        "yaml_definition_version": yaml_v,
        "yaml_matches_active": bool(yaml_v and active and yaml_v == active),
        "serving": serving,
        "serving_superseded": models.serving_superseded(serving),
        "verdict": ledger.verdict_brief(),
        "activity": _activity(),
        "budget": {"month_to_date_usd": round(ops.month_to_date_usd(), 4), "hard_stop_usd": ops.hard_stop_usd()},
        "decisions_waiting": len(approvals.waiting_items()),
        "alerts_open": ops.open_alerts(),
        "api": {"live": False, "p99_ms": None, "fallback_rate": None},
        "feed": {
            "live": False,
            "last_received_at": iso(latest_data["created_at"]) if latest_data else None,
            "quality_failures": None,
        },
    }


def snapshot_state() -> dict:
    """Where the console's data comes from and how fresh it is."""
    from lau.console.actions import mirror_mode
    from lau.console.snapshot import mirror

    if mirror_mode():
        m = mirror()
        st = m.state if m else {}
        return {
            "mode": "mirror",
            "published_at": st.get("published_at"),
            "synced_at": st.get("synced_at"),
            "error": st.get("error"),
        }
    mode = "direct" if get_settings().project.backend == "databricks" else "fixture"
    return {"mode": mode, "published_at": None, "synced_at": None, "error": None}


@router.get("/status")
def status(request: Request) -> dict:
    return {
        **_status_core(),
        "actions_enabled": deps.actions_enabled(),
        "user": deps.current_user(request),
        "snapshot": snapshot_state(),
    }


def _status_sentence(core: dict) -> str:
    parts = []
    serving = core["serving"]
    if serving:
        sup = " (trained under a superseded definition)" if core["serving_superseded"] else ""
        parts.append(f"Decisions use {serving['label']}{sup}.")
    else:
        parts.append("No model has been promoted, so decisions still use the legacy policy score.")
    d = core["active_definition"]
    if d:
        parts.append(f"Default is defined as {d['summary']} ({d['short']}).")
    if core["verdict"]:
        parts.append(core["verdict"]["title"].rstrip(".") + ".")
    act = core["activity"]
    if act["state"] == "cycle_running":
        parts.append(f"An improvement cycle is running ({act.get('step') or 'starting'}).")
    elif act["state"] == "pipeline_rebuilding":
        parts.append(f"The pipeline is rebuilding ({act.get('step')}).")
    n = core["decisions_waiting"]
    if n:
        parts.append(f"{n} decision{'s' if n != 1 else ''} waiting.")
    high = core["alerts_open"]["high"]
    if high:
        parts.append(f"{high} high-severity alert{'s' if high != 1 else ''} open.")
    return " ".join(parts)


def _tiles(core: dict) -> list[dict]:
    led = ledger.latest() or {}
    den = led.get("denominator") or {}
    active = defs.active_version()
    tiles = []
    v = core["verdict"]
    tone = {"improved": "good", "regressed": "crit", "not_best": "warn", "no_change": "neutral"}
    tiles.append(
        {
            "key": "verdict",
            "label": "Is it improving?",
            "value": VERDICT_LABELS.get(v["code"], v["code"]) if v else "No evidence yet",
            "sub": v["title"] if v else "Run lau evidence run",
            "tone": tone.get(v["code"], "neutral") if v else "neutral",
            "href": "/progress",
        }
    )
    serving = core["serving"]
    tiles.append(
        {
            "key": "serving",
            "label": "Making decisions",
            "value": serving["label"] if serving else models.REFERENCE_LABEL,
            "sub": "superseded definition"
            if core["serving_superseded"]
            else ("champion" if serving else "no promotion yet"),
            "tone": "warn" if core["serving_superseded"] else ("accent" if serving else "neutral"),
            "href": f"/models/{serving['name']}/{serving['version']}" if serving else "/models",
        }
    )
    best = models.ref_from_key(led.get("best_known_key"), led.get("best_known_label"))
    lift = led.get("lift_estimate")
    tiles.append(
        {
            "key": "best_known",
            "label": "Best known model",
            "value": best["label"] if best else "—",
            "sub": f"AUC lift vs legacy {lift:+.3f}" if lift is not None else None,
            "tone": "neutral",
            "href": f"/models/{best['name']}/{best['version']}"
            if best and best["kind"] != "reference"
            else "/progress",
        }
    )
    d = core["active_definition"]
    tiles.append(
        {
            "key": "definition",
            "label": "Definition of default",
            "value": d["summary"] if d else "None active",
            "sub": d["short"] if d else None,
            "tone": "neutral" if core["yaml_matches_active"] else "warn",
            "href": f"/definitions/{d['version']}" if d else "/definitions",
        }
    )
    tiles.append(
        {
            "key": "tests",
            "label": "Validation tests since reset",
            "value": str(den.get("tests_since_reset", 0)),
            "sub": f"next margin {den['next_margin']:.4f}" if den.get("next_margin") is not None else None,
            "tone": "neutral",
            "href": "/performance",
        }
    )
    used, budget = evals.holdout_used(active), evals.holdout_budget()
    tiles.append(
        {
            "key": "holdout",
            "label": "Holdout gates used",
            "value": f"{used} of {budget}",
            "sub": "per definition",
            "tone": "warn" if budget and used >= budget else "neutral",
            "href": "/performance",
        }
    )
    b = core["budget"]
    share = b["month_to_date_usd"] / b["hard_stop_usd"] if b["hard_stop_usd"] else 0.0
    tiles.append(
        {
            "key": "spend",
            "label": "Spend this month",
            "value": f"${b['month_to_date_usd']:,.2f}",
            "sub": f"of ${b['hard_stop_usd']:,.0f} hard stop",
            "tone": "crit" if share >= 0.9 else ("warn" if share >= 0.7 else "neutral"),
            "href": "/cost",
        }
    )
    a = core["alerts_open"]
    tiles.append(
        {
            "key": "alerts",
            "label": "Open alerts",
            "value": str(a["high"] + a["medium"]),
            "sub": f"{a['high']} high, {a['medium']} medium",
            "tone": "crit" if a["high"] else ("warn" if a["medium"] else "good"),
            "href": "/alerts",
        }
    )
    return tiles


@router.get("/overview")
def overview() -> dict:
    core = _status_core()
    return {
        "status_sentence": _status_sentence(core),
        "tiles": _tiles(core),
        "waiting": approvals.waiting_items(),
        "recent_events": events.page(limit=12, exclude_quiet=True)["events"],
        "pipeline": ops.freshness(defs.active_version()),
    }
