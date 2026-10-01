"""What is waiting for a person, and the evidence packet behind each promotion decision.

A candidate waits for a decision when it passed validation and carries both a red-team and a compliance report,
and nobody has approved or rejected it yet. The packet says exactly what is missing before each next step.
"""

from __future__ import annotations

from lau.console import deps
from lau.console.services import benchmark, config, evals, ledger, models, ops, reports
from lau.console.services import definitions as defs
from lau.console.util import boolean, iso, now_utc, num, text

VERDICT_TONE = {"pass": "good", "ok": "good", "concern": "warn", "fail": "crit", "block": "crit"}


def _verdict_badge(role: str, verdict: str | None) -> dict:
    if not verdict:
        return {"label": f"{role}: no report", "tone": "neutral"}
    return {"label": f"{role}: {verdict}", "tone": VERDICT_TONE.get(verdict, "neutral")}


def _gate_badge(gate: dict | None) -> dict:
    if gate is None:
        return {"label": "Holdout gate not run", "tone": "neutral"}
    return {
        "label": "Holdout gate passed" if gate["passed"] else "Holdout gate failed",
        "tone": "good" if gate["passed"] else "crit",
    }


def pending_candidates() -> list[dict]:
    """Evaluation rows of candidates waiting for a human decision under the active definition, newest first.

    Candidates of a superseded definition are not waiting: promoting one could never make it serve. They stay
    reachable from their model card.
    """
    df = evals.latest_per_ref(evals.evaluations())
    active = defs.active_version()
    if df.empty or not active:
        return []
    out = []
    for r in df.to_dict("records"):
        ref = str(r["candidate_ref"])
        if not ref.startswith("candidate:") or not r.get("passed_validation") or r.get("definition_version") != active:
            continue
        verdicts = reports.review_verdicts(ref)
        if verdicts["redteam"] is None or verdicts["compliance"] is None:
            continue
        if evals.latest_approval_row(ref) is not None:
            continue
        if models.promotion_for_candidate(ref.partition(":")[2]):
            continue
        out.append({**r, "_verdicts": verdicts})
    return out


def waiting_items() -> list[dict]:
    items = []
    active = defs.active_version()
    best = (ledger.latest() or {}).get("best_known_key")
    for r in pending_candidates():
        ref = str(r["candidate_ref"])
        model = models.ref_for_candidate(ref)
        v = r["_verdicts"]
        gate_row = evals.latest_gate_row(ref)
        badges = [
            {"label": "Validation passed", "tone": "good"},
            _verdict_badge("Red team", v["redteam"]["verdict"]),
            _verdict_badge("Compliance", v["compliance"]["verdict"]),
            _gate_badge(evals.gate_summary(gate_row) if gate_row else None),
        ]
        beats = benchmark.beats_best_known(model["key"], best)
        if beats is False:
            badges.append({"label": "Not the best known model", "tone": "warn"})
        created = max(x for x in (iso(r["ts"]), v["redteam"]["created_at"], v["compliance"]["created_at"]) if x)
        items.append(
            {
                "id": f"promotion:{ref}",
                "kind": "promotion",
                "title": f"Promote {model['label']} to champion?",
                "created_at": created,
                "badges": badges,
                "href": f"/approvals/{ref}",
            }
        )
    yaml_v = config.yaml_definition_version()
    if yaml_v and active and yaml_v != active:
        items.append(
            {
                "id": f"definition_change:{yaml_v}",
                "kind": "definition_change",
                "title": "The definition in config/default_definition.yaml differs from the active one",
                "created_at": iso(now_utc()),
                "badges": [{"label": "Run lau default-definition plan, then apply", "tone": "warn"}],
                "href": "/definitions",
            }
        )
    return items


def evidence_packet(candidate_ref: str) -> dict | None:
    row, res = evals.latest_result(candidate_ref)
    if row is None:
        return None
    model = models.ref_for_candidate(candidate_ref)
    version = str(row["definition_version"])
    summary = evals.summary_from_row(row)
    verdicts = reports.review_verdicts(candidate_ref)
    gate_row = evals.latest_gate_row(candidate_ref)
    gate = evals.gate_summary(gate_row) if gate_row else None
    approval = evals.latest_approval_row(candidate_ref)
    promoted = models.promotion_for_candidate(candidate_ref.partition(":")[2])
    best_key = (ledger.latest() or {}).get("best_known_key")
    fairness = res.get("fairness") or {}
    tags = (models.registry_row(model["name"], model["version"]) or {}).get("tags") or {}
    enabled = deps.actions_enabled()
    used, budget = evals.holdout_used(version), evals.holdout_budget()

    blockers: list[str] = []
    if not summary["passed_validation"]:
        blockers.append("It did not pass validation.")
    for kind, label in (("redteam", "red-team"), ("compliance", "compliance")):
        if verdicts[kind] is None:
            blockers.append(f"No {label} report yet.")
    if verdicts["compliance"] and verdicts["compliance"]["verdict"] == "block":
        blockers.append("Compliance blocked it.")
    if gate is None and used >= budget:
        blockers.append(f"The holdout budget for this definition is used up ({used} of {budget}).")
    if gate is not None and not gate["passed"]:
        blockers.append("It failed the holdout gate.")
    if promoted:
        blockers.append("Already promoted.")
    ready_for_gate = not blockers and gate is None
    gate_ok = gate is not None and gate["passed"]
    decided_on_gate = approval is not None and gate_row is not None and approval.get("gate_id") == gate_row["gate_id"]
    approved = decided_on_gate and approval.get("decision") == "approve"
    if not enabled:
        blockers.append("Actions are disabled on this console.")
    return {
        "candidate_ref": candidate_ref,
        "model": model,
        "definition_version": version,
        "evaluation": summary,
        "checks": {str(k): bool(v) for k, v in (res.get("checks") or {}).items()},
        "benchmark": {
            "row": benchmark.row_for_key(model["key"]),
            "best_known": models.ref_from_key(best_key, (ledger.latest() or {}).get("best_known_label")),
            "beats_best_known": benchmark.beats_best_known(model["key"], best_key),
        },
        "gate": gate,
        "reports": reports.for_candidate(candidate_ref),
        "fairness_min_air": num(fairness.get("min_air")),
        "cost_usd": ops.cycle_cost_usd(tags.get("cycle_id")),
        "decision": evals.approval_record(approval) if approval else None,
        "promotion": _promotion(promoted),
        "holdout": {"used": used, "budget": budget},
        "can_run_gate": enabled and ready_for_gate,
        "can_decide": enabled and gate_ok and not decided_on_gate and not promoted,
        "can_promote": enabled and approved and not promoted,
        "blockers": blockers,
    }


def _promotion(r: dict | None) -> dict | None:
    if not r:
        return None
    return {
        "promotion_id": str(r["promotion_id"]),
        "ts": iso(r["ts"]),
        "definition_version": str(r["definition_version"]),
        "production_model_version": str(r["production_model_version"]),
        "candidate_model_version": str(r["candidate_model_version"]),
        "previous_champion_version": text(r.get("previous_champion_version")),
        "serving": bool(boolean(r.get("serving"))),
        "approval_id": str(r.get("approval_id") or ""),
    }


def model_version_of(candidate_ref: str) -> str:
    prefix, _, version = candidate_ref.partition(":")
    if prefix != "candidate" or not version.isdigit():
        raise ValueError(f"not a candidate ref: {candidate_ref}")
    return version


def decision_payload(body: dict) -> tuple[str, str]:
    decision = str(body.get("decision") or "")
    rationale = str(body.get("rationale") or "").strip()
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be approve or reject")
    if len(rationale) < 10:
        raise ValueError("a rationale of at least 10 characters is required")
    return decision, rationale


def gate_id_for(candidate_ref: str) -> tuple[str, str] | None:
    """(gate_id, definition_version) of the latest gate of a candidate, if any."""
    g = evals.latest_gate_row(candidate_ref)
    return None if g is None else (str(g["gate_id"]), str(g["definition_version"]))
