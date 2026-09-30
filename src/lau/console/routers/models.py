"""Console API (screen 8, models): GET /api/models, GET /api/models/{name}/{version}.

The registry is read from ops.model_registry (mirrored from MLflow by the evidence job); the console never calls MLflow.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import HTTPException

from lau.console import deps
from lau.console.services import benchmark, evals, models, reports
from lau.console.util import api_router, integer, iso, read_table, sql_str, text

router = api_router()


def _eval_ref(row: dict) -> str:
    """The evaluation ref of a registry row (production versions are evaluated as their source candidate)."""
    cand_name, prod_name = models.names()
    version = row.get("source_candidate_version") if row["model_name"] == prod_name else row["version"]
    role = row.get("lau_role")
    if row["model_name"] == prod_name:
        src = models.registry_row(cand_name, str(version)) or {}
        role = src.get("lau_role")
    return f"{'baseline' if role == 'baseline' else 'candidate'}:{version}"


def _status(row: dict) -> str:
    s = row.get("status")
    return s if s in models.MODEL_STATUSES else "candidate"


@router.get("/models")
def model_list() -> list[dict]:
    reg = models.registry()
    if reg.empty:
        return []
    ev = evals.latest_per_ref(evals.evaluations())
    by_ref = {str(r["candidate_ref"]): r for r in ev.to_dict("records")} if len(ev) else {}
    out = []
    for r in reg.to_dict("records"):
        e = by_ref.get(_eval_ref(r))
        tags = r.get("tags") or {}
        out.append(
            {
                "model": models.ref_from_row(r),
                "status": _status(r),
                "aliases": list(r.get("aliases") or []),
                "created_at": iso(r.get("created_at")),
                "model_type": text(tags.get("model_type")),
                "n_features": integer(tags.get("n_features")),
                "val_auc": e.get("val_auc") if e else None,
                "passed_validation": bool(e["passed_validation"])
                if e and e.get("passed_validation") is not None
                else None,
                "author": text(tags.get("author")),
                "cycle_id": text(tags.get("cycle_id")),
            }
        )
    return out


def _engineered(names: list[str]) -> list[dict]:
    if not names:
        return []
    listed = ", ".join(sql_str(n) for n in names)
    df = read_table(
        deps.ui_store(),
        "feature_registry",
        "features",
        columns=["name", "expression", "rationale", "created_at"],
        where=f"name IN ({listed})",
        ts=["created_at"],
    )
    if df.empty:
        return [{"name": n, "expression": "", "rationale": ""} for n in names]
    df = df.sort_values("created_at").groupby("name").tail(1)
    found = {str(r["name"]): r for r in df.to_dict("records")}
    return [
        {
            "name": n,
            "expression": str(text((found.get(n) or {}).get("expression")) or ""),
            "rationale": str(text((found.get(n) or {}).get("rationale")) or ""),
        }
        for n in names
    ]


@router.get("/models/{name}/{version}")
def model_card(name: str, version: str) -> dict:
    row = models.registry_row(name, version)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown model version")
    ref = _eval_ref(row)
    ev = evals.evaluations()
    mine = ev[ev["candidate_ref"] == ref] if len(ev) else ev
    _, res = evals.latest_result(ref)
    m = res.get("model") or {}
    gate = evals.latest_gate_row(ref)
    model = models.ref_from_row(row)
    return {
        "model": model,
        "status": _status(row),
        "aliases": list(row.get("aliases") or []),
        "tags": {str(k): str(v) for k, v in (row.get("tags") or {}).items()},
        "description": {
            "model_type": str(m.get("model_type") or (row.get("tags") or {}).get("model_type") or ""),
            "params": m.get("params") or {},
            "features": [str(x) for x in m.get("features") or []],
            "engineered": [str(x) for x in m.get("engineered") or []],
        }
        if m
        else None,
        "engineered": _engineered([str(x) for x in m.get("engineered") or []]),
        "evaluations": evals.summaries(mine),
        "gate": evals.gate_summary(gate) if gate else None,
        "reports": reports.for_candidate(ref),
        "approvals": evals.approvals_for(ref),
        "benchmark": benchmark.row_for_key(model["key"]),
        "feature_importance": evals.feature_importance(res),
    }
