"""Console API (screen 9, performance): GET /api/performance?[def], GET /api/evaluations/{eval_id}.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import HTTPException

from lau.console.services import definitions as defs
from lau.console.services import evals
from lau.console.util import DEF_PARAM, api_router, safe_token

router = api_router()


@router.get("/performance")
def performance(version: str | None = DEF_PARAM) -> dict:
    v = defs.resolve_or_404(version)
    ev = evals.evaluations()
    mine = ev[ev["definition_version"] == v] if len(ev) else ev
    ledger_rows = []
    for r in mine.sort_values("ts").to_dict("records") if len(mine) else []:
        s = evals.summary_from_row(r)
        ledger_rows.append(
            {
                "n_tests": s["n_tests"],
                "required_margin": s["required_margin"],
                "reference_auc": s["reference_auc"],
                "candidate_ref": s["candidate_ref"],
                "val_auc": s["val_auc"],
                "passed": s["passed_validation"],
                "ts": s["ts"],
            }
        )
    from lau.console import deps
    from lau.console.services import config
    from lau.harness import multiple_testing

    since = multiple_testing.n_tests(deps.ui_store(), v) if v else 0
    gates = evals.gates()
    mine_gates = gates[gates["definition_version"] == v] if len(gates) else gates
    return {
        "definition_version": v,
        "definitions": defs.definition_refs(),
        "tests_since_reset": since,
        "next_margin": multiple_testing.required_margin(since + 1, config.thresholds().get("gate", {})) if v else None,
        "evaluations": evals.summaries(mine),
        "ledger": ledger_rows,
        "holdout": {
            "used": evals.holdout_used(v),
            "budget": evals.holdout_budget(),
            "gates": [evals.gate_summary(r) for r in mine_gates.to_dict("records")] if len(mine_gates) else [],
        },
    }


@router.get("/evaluations/{eval_id}")
def evaluation(eval_id: str) -> dict:
    if not safe_token(eval_id):
        raise HTTPException(status_code=400, detail="invalid evaluation id")
    detail = evals.evaluation_detail(eval_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="unknown evaluation")
    return detail
