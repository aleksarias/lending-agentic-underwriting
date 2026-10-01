"""Console API: GET /api/progress (screen 4: is the system improving?).

Everything here is a measurement: the verdict and guardrails come from ops.improvement_ledger, the matrix and the
paired differences from ops.benchmark_results (all models re-scored under the same frozen benchmark definitions),
process health from cycles, evaluations and the cost log.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

import pandas as pd

from lau.console import deps
from lau.console.services import benchmark, evals, feedback, ledger, models, ops
from lau.console.util import api_router, integer, num, read_table, text

router = api_router()


def _ledger_rows() -> pd.DataFrame:
    return read_table(deps.ui_store(), "ops", "improvement_ledger", ts=["computed_at"])


def _lineage(df: pd.DataFrame) -> list[dict]:
    """Best known model's lift over the frozen reference, one point per day (the day's last evidence run)."""
    if df.empty:
        return []
    df = df.sort_values("computed_at")
    df = df[df["lift_estimate"].notna()]
    if df.empty:
        return []
    df = df.assign(day=df["computed_at"].dt.strftime("%Y-%m-%d")).groupby("day").tail(1)
    out, prev_def, prev_serving = [], None, None
    for r in df.to_dict("records"):
        definition = str(text(r.get("active_definition")) or "")
        serving = text(r.get("serving_key"))
        event = None
        if prev_def is not None and definition != prev_def:
            event = "definition_change"
        elif prev_serving is not None and serving != prev_serving:
            event = "promotion"
        prev_def, prev_serving = definition, serving
        est = num(r["lift_estimate"]) or 0.0
        out.append(
            {
                "period": str(r["day"]),
                "model": models.ref_from_key(text(r.get("best_known_key")), text(r.get("best_known_label")))
                or models.reference_ref(),
                "lift_vs_reference": {
                    "estimate": est,
                    "lo": num(r.get("lift_lo")) if num(r.get("lift_lo")) is not None else est,
                    "hi": num(r.get("lift_hi")) if num(r.get("lift_hi")) is not None else est,
                },
                "definition_version": definition,
                "event": event,
            }
        )
    return out


def _process_health() -> dict:
    cycles = ops.cycles()
    ev = evals.evaluations()
    cost = ops.cost_log()
    cand = ev[ev["candidate_ref"].astype(str).str.startswith("candidate:")] if len(ev) else ev
    passed = cand[cand["passed_validation"].fillna(False).astype(bool)] if len(cand) else cand
    anthropic = float(cost.loc[cost["kind"] == "anthropic", "usd"].fillna(0).sum()) if len(cost) else 0.0
    total_cost = float(cost["usd"].fillna(0).sum()) if len(cost) else 0.0
    months: dict[str, dict] = {}

    def bucket(m: str) -> dict:
        return months.setdefault(m, {"month": m, "cycles": 0, "passed": 0, "cost_usd": 0.0})

    for ts in cycles["started_at"] if len(cycles) else []:
        bucket(ts.strftime("%Y-%m"))["cycles"] += 1
    for ts in passed["ts"] if len(passed) else []:
        bucket(ts.strftime("%Y-%m"))["passed"] += 1
    for ts, usd in zip(cost["ts"], cost["usd"].fillna(0), strict=True) if len(cost) else []:
        bucket(ts.strftime("%Y-%m"))["cost_usd"] += float(usd)
    return {
        "cycles_total": len(cycles),
        "cycles_completed": int((cycles["status"] == "completed").sum()) if len(cycles) else 0,
        "candidates_evaluated": len(cand),
        "candidates_passed": len(passed),
        "anthropic_usd_total": round(anthropic, 4),
        "cost_per_passed_candidate": round(total_cost / len(passed), 4) if len(passed) else None,
        "months": [{**m, "cost_usd": round(m["cost_usd"], 4)} for _, m in sorted(months.items())],
    }


def _denominator(row: dict | None) -> dict | None:
    if not row or not row.get("denominator"):
        return None
    d = row["denominator"]
    return {
        "definition_version": str(d.get("definition_version") or ""),
        "tests_since_reset": integer(d.get("tests_since_reset")) or 0,
        "tests_total": integer(d.get("tests_total")) or 0,
        "next_margin": num(d.get("next_margin")) or 0.0,
        "holdout_used": integer(d.get("holdout_used")) or 0,
        "holdout_budget": integer(d.get("holdout_budget")) or 0,
        "candidates": [
            {"ref": str(c.get("ref")), "auc": num(c.get("auc")), "passed": c.get("passed"), "ts": c.get("ts")}
            for c in d.get("candidates") or []
        ],
    }


def _guardrails(row: dict | None) -> list[dict]:
    out = []
    for g in (row or {}).get("guardrails") or []:
        status = str(g.get("status") or "unknown")
        out.append(
            {
                "key": str(g.get("key")),
                "label": str(g.get("label")),
                "value": num(g.get("value")),
                "threshold": num(g.get("threshold")),
                "direction": "min" if g.get("direction") == "min" else "max",
                "status": status if status in ("ok", "watch", "breach", "unknown") else "unknown",
                "history": [
                    {"ts": h.get("ts"), "value": num(h.get("value"))}
                    for h in g.get("history") or []
                    if num(h.get("value")) is not None
                ],
            }
        )
    return out


@router.get("/progress")
def progress() -> dict:
    row = ledger.latest()
    return {
        "verdict": ledger.verdict_payload(),
        "benchmark": benchmark.matrix(),
        "reference_diffs": benchmark.diffs("auc_minus_reference"),
        "best_known_diffs": benchmark.diffs("auc_minus_best_known"),
        "lineage": _lineage(_ledger_rows()),
        "guardrails": _guardrails(row),
        "process_health": _process_health(),
        "denominator": _denominator(row),
        "production": feedback.production_evidence(),
    }
