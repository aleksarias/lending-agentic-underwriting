"""Promotion gate: the ONLY code path that reads the out-of-time holdout, and only at promotion time.

Checks (all deterministic):
  1. validation checks re-run (not counted as a new test)
  2. holdout budget for the definition version not exhausted
  3. holdout AUC >= reference holdout AUC - tolerance (reference = same-version champion, else baseline)
  4. holdout calibration and through-the-door adverse impact in the OOT window
Results are written to ops.gate_results; the promotion job requires a passing gate row.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pandas as pd

from lau.harness import fairness, metrics
from lau.harness.evaluate import _json_default, evaluate_model, reference_metrics, window_population
from lau.harness.holdout import _issue, holdout_months, read_holdout
from lau.modeling.registry_io import DefinitionMismatchError, champion_for, load_pd_model
from lau.settings import get_settings
from lau.store import get_store


class GateBudgetExceededError(RuntimeError):
    pass


def holdout_uses(store, version: str) -> int:
    if not store.table_exists("ops", "gate_results"):
        return 0
    df = store.query(
        f"SELECT count(*) AS n FROM {store.fq('ops', 'gate_results')} WHERE definition_version = '{version}'"
    )
    return int(df["n"].iloc[0])


def promotion_gate(model, version: str, candidate_ref: str) -> dict:
    s = get_settings()
    store = get_store("harness")
    th, fcfg = s.thresholds["gate"], s.thresholds["fairness"]
    if model.definition_version != version:
        raise DefinitionMismatchError("candidate and gate definition versions differ")
    max_uses = s.budgets["holdout"]["max_gate_evaluations_per_definition"]
    used = holdout_uses(store, version)
    if used >= max_uses:
        raise GateBudgetExceededError(f"holdout budget exhausted for {version}: {used}/{max_uses} gate runs")

    val = evaluate_model(model, version, candidate_ref, count_test=False)

    token = _issue("promotion_gate", candidate_ref)
    hold = read_holdout(store, version, token)
    y = hold["label"].to_numpy()
    p = model.predict_pd(hold)
    cand = metrics.summary(y, p)

    champ = champion_for(version)
    if champ is not None:
        ref_kind, ref_mv, ref_model = "champion", champ[0], champ[1]
    else:
        ref = reference_metrics(store, version)
        if not ref or not ref.get("baseline_model_version"):
            raise RuntimeError(f"no reference (champion or baseline) for {version}; run the pipeline first")
        from lau.modeling.registry_io import candidate_uri

        ref_kind, ref_mv = "baseline", str(ref["baseline_model_version"])
        ref_model = load_pd_model(candidate_uri(ref_mv), "harness")
    if ref_model.definition_version != version:
        raise DefinitionMismatchError("reference model belongs to another definition version")
    ref_auc = metrics.auc(y, ref_model.predict_pd(hold))

    oot_start, oot_end = holdout_months(store, version)
    pop = window_population(store, oot_start, oot_end)
    fair = fairness.adverse_impact(
        pd.DataFrame({"application_id": pop["application_id"], "pd": model.predict_pd(pop)}),
        fairness.protected_frame(store),
        s.protected["protected_classes"],
        fcfg["approval_rate"],
    )
    checks = {
        "validation_checks": bool(val["passed_validation"]),
        "holdout_auc_vs_reference": bool(cand["auc"] >= ref_auc - th["holdout_auc_tolerance"]),
        "holdout_calibration": bool(cand["ece"] <= th["max_ece"] * 1.5),
        "holdout_adverse_impact": bool(fair["min_air"] >= fcfg["min_air"]),
    }
    result = {
        "gate_id": f"gate-{uuid.uuid4().hex[:10]}",
        "candidate_ref": candidate_ref,
        "definition_version": version,
        "ts": datetime.now(UTC).isoformat(),
        "holdout": cand,
        "reference": {"kind": ref_kind, "model_version": ref_mv, "holdout_auc": ref_auc},
        "holdout_fairness_min_air": fair["min_air"],
        "validation_eval_id": val["eval_id"],
        "checks": checks,
        "passed": all(checks.values()),
        "holdout_uses_after": used + 1,
    }
    store.write_df(
        "ops",
        "gate_results",
        pd.DataFrame(
            [
                {
                    "gate_id": result["gate_id"],
                    "candidate_ref": candidate_ref,
                    "definition_version": version,
                    "ts": datetime.now(UTC),
                    "passed": result["passed"],
                    "holdout_auc": cand["auc"],
                    "reference_holdout_auc": ref_auc,
                    "result_json": json.dumps(result, default=_json_default),
                }
            ]
        ),
        mode="append",
    )
    return result


def latest_gate(store, candidate_ref: str) -> dict | None:
    if not store.table_exists("ops", "gate_results"):
        return None
    df = store.query(
        f"SELECT result_json FROM {store.fq('ops', 'gate_results')} WHERE candidate_ref = '{candidate_ref}' "
        "ORDER BY ts DESC LIMIT 1"
    )
    return None if df.empty else json.loads(df["result_json"].iloc[0])
