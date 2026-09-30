"""The verdict: is the system improving? -> `ops.improvement_ledger` (one row per evidence run).

Deterministic rules over the benchmark ledger, evaluated in order (no LLM anywhere):

  1. no model other than the frozen reference was scored                        -> insufficient_evidence
  2. the newest challenger (latest `candidate:*` evaluation under the active definition) exists, was scored and is
     not the best known model under the primary benchmark                       -> not_best
  3. a model is serving (alias `champion`): its lift over the reference (primary benchmark, paired bootstrap CI)
       entirely above 0 and no guardrail breached                               -> improved
       entirely below 0, or any guardrail breached                              -> regressed
       otherwise (interval straddles 0)                                         -> no_change
  4. nothing is serving                                                         -> insufficient_evidence, stating
     the best known model's lift over the reference

Guardrails and the multiple-testing denominator ride along as JSON so the console can show what the verdict rests on.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from lau.evidence import ledger, registry_sync, schemas
from lau.evidence.config import REFERENCE_LABEL
from lau.evidence.context import EvidenceContext
from lau.evidence.stats import Estimate
from lau.harness import multiple_testing
from lau.modeling import registry_io

THIN_FILE_WATCH_AUC = 0.65  # thin-file AUC below this is a "watch" item, not a breach
REASON_CODE_COVERAGE_MIN = 0.99  # mirrors the `reason_codes` validation check
MAX_DENOMINATOR_CANDIDATES = 200  # cap on the evaluation list carried in denominator_json
EPS = 1e-12


@dataclass(frozen=True)
class Guardrail:
    key: str
    label: str
    metric: str  # in ops.evaluation_metrics
    direction: str  # "max": value must stay at or below the threshold; "min": at or above
    threshold: Callable[[dict], float]
    watch_only: bool = False  # a violation is a "watch", never a "breach"


GUARDRAILS = [
    Guardrail("ece", "Calibration error (ECE)", "validation.ece", "max", lambda t: t["gate"]["max_ece"]),
    Guardrail("thin_file_auc", "Thin-file AUC", "thin_file_auc", "min", lambda t: THIN_FILE_WATCH_AUC, True),
    Guardrail("min_air", "Min adverse impact ratio", "fairness.min_air", "min", lambda t: t["fairness"]["min_air"]),
    Guardrail(
        "score_psi",
        "Score PSI (train vs validation)",
        "score_psi_train_val",
        "max",
        lambda t: t["gate"]["max_score_psi"],
    ),
    Guardrail(
        "reason_code_coverage",
        "Reason-code coverage",
        "reason_code_quality.coverage_any",
        "min",
        lambda t: REASON_CODE_COVERAGE_MIN,
    ),
]


# ---- helpers --------------------------------------------------------------------------------------------------
def _iso(ts) -> str | None:
    if ts is None or pd.isna(ts):
        return None
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t.isoformat()


def _clean(o):
    """JSON-safe copy: numpy scalars to Python, NaN/inf to None, timestamps to ISO-8601 UTC."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_clean(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, datetime | pd.Timestamp):
        return _iso(o)
    return o


def _dumps(o) -> str:
    return json.dumps(_clean(o), allow_nan=False, sort_keys=False)


def evaluation_refs(version: str | None) -> list[str]:
    return [] if not version else [f"candidate:{version}", f"baseline:{version}"]


def refs_for_key(key: str, registry: list[registry_sync.RegistryVersion]) -> list[str]:
    """Evaluation refs of a model key: a candidate's own version, a production copy's source candidate."""
    name, version = ledger.split_model_key(key)
    for v in registry:
        if v.key == key:
            return evaluation_refs(version if v.registry == "candidate" else v.source_candidate_version)
    return evaluation_refs(version) if name == registry_io.candidate_model_name() else []


# ---- guardrails -----------------------------------------------------------------------------------------------
def guardrail_status(g: Guardrail, value: float | None, threshold: float) -> str:
    if value is None or not math.isfinite(value):
        return "unknown"
    ok = value <= threshold if g.direction == "max" else value >= threshold
    if ok:
        return "ok"
    return "watch" if g.watch_only else "breach"


def guardrails(metrics: pd.DataFrame, refs: list[str], thresholds: dict) -> list[dict]:
    """Guardrail rows for the latest evaluation among `refs`; history = that definition's earlier evaluations."""
    latest = None
    if refs and not metrics.empty:
        mine = metrics[metrics["candidate_ref"].isin(refs)]
        if not mine.empty:
            latest = mine.sort_values("ts", kind="stable").iloc[-1]
    out = []
    for g in GUARDRAILS:
        value, history = None, []
        if latest is not None:
            cur = metrics[(metrics["eval_id"] == latest["eval_id"]) & (metrics["metric"] == g.metric)]
            value = float(cur["value"].iloc[0]) if len(cur) else None
            past = metrics[
                (metrics["metric"] == g.metric)
                & (metrics["definition_version"] == latest["definition_version"])
                & (metrics["ts"] < latest["ts"])
            ].sort_values("ts", kind="stable")
            history = [{"ts": _iso(t), "value": float(v)} for t, v in zip(past["ts"], past["value"], strict=True)]
        threshold = float(g.threshold(thresholds))
        out.append(
            {
                "key": g.key,
                "label": g.label,
                "value": value,
                "threshold": threshold,
                "direction": g.direction,
                "status": guardrail_status(g, value, threshold),
                "history": history,
            }
        )
    return out


def _breaches(rows: list[dict] | None) -> list[dict]:
    return [r for r in rows or [] if r["status"] == "breach"]


# ---- decision -------------------------------------------------------------------------------------------------
def _estimate(rows: pd.DataFrame, key: str | None, metric: str, bench: str) -> Estimate | None:
    if key is None:
        return None
    r = rows[(rows["model_key"] == key) & (rows["metric"] == metric) & (rows["benchmark_key"] == bench)]
    if r.empty or pd.isna(r["value"].iloc[0]):
        return None
    x = r.iloc[0]
    return Estimate(float(x["value"]), float(x["ci_lo"]), float(x["ci_hi"]))


def _ci(e: Estimate, level: float) -> str:
    return f"{level:.0%} CI {e.lo:+.3f} to {e.hi:+.3f}"


def decide(
    *,
    bench: pd.DataFrame,
    primary_key: str,
    reference_key: str,
    level: float,
    serving_key: str | None,
    challenger_key: str | None,
    challenger_label: str | None,
    guardrails_by_key: dict[str, list[dict]],
) -> dict:
    """Apply the rules to one run's benchmark rows. Pure: no I/O, so every branch is unit-testable."""
    out: dict = {
        "verdict_code": "insufficient_evidence",
        "title": "Not enough evidence yet",
        "detail": f"No benchmark results exist for the primary benchmark ({primary_key}); run `lau evidence run`.",
        "best_known_key": None,
        "best_known_label": None,
        "newest_challenger_key": challenger_key,
        "newest_challenger_label": challenger_label,
        "serving_key": serving_key,
        "lift": None,
        "guardrails": [],
    }
    primary = bench[bench["benchmark_key"] == primary_key] if len(bench) else bench
    if primary.empty:
        return out
    label = dict(zip(primary["model_key"], primary["model_label"], strict=True))
    auc = {r.model_key: r.value for r in primary[primary["metric"] == "auc"].itertuples()}
    ref = primary[(primary["model_key"] == reference_key) & (primary["metric"] == "auc")]
    window = primary.iloc[0]
    where = (
        f"the {int(window['benchmark_dpd'])} DPD benchmark ({window['window_start']} to {window['window_end']} "
        f"originations, {int(window['n']):,} loans)"
    )
    out["newest_challenger_label"] = label.get(challenger_key, challenger_label) if challenger_key else None
    best = ledger.best_known(primary, primary_key, reference_key)
    if best is None:
        out["detail"] = f"Only the frozen {REFERENCE_LABEL} has been scored on {where}; no registered model to compare."
        return out
    best_key, best_label, best_auc = str(best["model_key"]), str(best["model_label"]), float(best["value"])
    ref_auc = float(ref["value"].iloc[0]) if len(ref) else float("nan")
    out.update(best_known_key=best_key, best_known_label=best_label)

    def lift_of(key: str | None) -> Estimate | None:
        return _estimate(primary, key, "auc_minus_reference", primary_key)

    def lift_sentence(name: str, key: str) -> str:
        e = lift_of(key)
        head = f"On {where}, {name} scores AUC {auc[key]:.3f} versus {ref_auc:.3f} for the {REFERENCE_LABEL}"
        if e is None:
            return head + "."
        return f"{head}: lift {e.value:+.3f} ({_ci(e, level)})."

    # 2. the newest challenger is not the best known model
    if challenger_key and challenger_key in auc and auc[challenger_key] < best_auc - EPS:
        c_label = label[challenger_key]
        d = _estimate(primary, challenger_key, "auc_minus_best_known", primary_key)
        diff = f"{d.value:+.3f} ({_ci(d, level)})" if d else f"{auc[challenger_key] - best_auc:+.3f}"
        out.update(
            verdict_code="not_best",
            title=f"Newest challenger {c_label} is not the best known model",
            detail=(
                f"On {where}, {c_label} scores AUC {auc[challenger_key]:.3f}; the best known model, {best_label}, "
                f"scores {best_auc:.3f}. {c_label} minus {best_label}: {diff}."
            ),
            lift=lift_of(serving_key if serving_key in auc else best_key),
            guardrails=guardrails_by_key.get(challenger_key, []),
        )
        return out

    # 3. a model is serving
    if serving_key and serving_key in auc:
        s_label = label[serving_key]
        lift = lift_of(serving_key)
        gr = guardrails_by_key.get(serving_key, [])
        breached = _breaches(gr)
        out.update(lift=lift, guardrails=gr)
        if lift is None or not (math.isfinite(lift.lo) and math.isfinite(lift.hi)):
            out.update(
                title=f"Serving model {s_label} could not be compared with the {REFERENCE_LABEL}",
                detail=lift_sentence(s_label, serving_key) + " The interval is undefined on this window.",
            )
            return out
        worse = lift.hi < 0
        if worse or breached:
            reasons = []
            if worse:
                reasons.append(f"it scores below the {REFERENCE_LABEL}")
            if breached:
                reasons.append(
                    "guardrail breached: "
                    + "; ".join(f"{b['label']} {b['value']:.3f} vs limit {b['threshold']:.3f}" for b in breached)
                )
            title = (
                f"Serving model {s_label} is worse than the {REFERENCE_LABEL}"
                if worse
                else f"Serving model {s_label} breaches a guardrail"
            )
            out.update(
                verdict_code="regressed",
                title=title,
                detail=f"{lift_sentence(s_label, serving_key)} Regression because {' and '.join(reasons)}.",
            )
        elif lift.lo > 0:
            out.update(
                verdict_code="improved",
                title=f"Serving model {s_label} improves on the {REFERENCE_LABEL}",
                detail=f"{lift_sentence(s_label, serving_key)} No guardrail is breached.",
            )
        else:
            out.update(
                verdict_code="no_change",
                title=f"Serving model {s_label} is not measurably better than the {REFERENCE_LABEL}",
                detail=(
                    f"{lift_sentence(s_label, serving_key)} "
                    "The interval includes zero, so no difference is established."
                ),
            )
        return out

    # 4. nothing (scored) is serving
    lift = lift_of(best_key)
    out.update(
        title="Insufficient evidence: no model is serving"
        if not serving_key
        else "Insufficient evidence: the serving model could not be scored",
        detail=f"{lift_sentence(best_label, best_key)} "
        + (
            "No model is serving yet, so there is no production evidence."
            if not serving_key
            else f"The serving model {serving_key} is not in the benchmark ledger."
        ),
        lift=lift,
        guardrails=guardrails_by_key.get(best_key, []),
    )
    return out


# ---- denominator ----------------------------------------------------------------------------------------------
def denominator(ctx: EvidenceContext) -> dict:
    """What the validation-side evidence rests on: tests run, the next margin, the holdout budget, every evaluation."""
    st, version = ctx.store, ctx.active_version
    since = multiple_testing.n_tests(st, version)
    total = used = 0
    if st.table_exists("ops", "experiment_counter"):
        df = st.query(
            f"SELECT count(*) AS n FROM {st.fq('ops', 'experiment_counter')} "
            f"WHERE definition_version = '{version}' AND purpose = 'validation_test'"
        )
        total = int(df["n"].iloc[0])
    if st.table_exists("ops", "gate_results"):
        df = st.query(
            f"SELECT count(*) AS n FROM {st.fq('ops', 'gate_results')} WHERE definition_version = '{version}'"
        )
        used = int(df["n"].iloc[0])
    e = ctx.evaluations
    e = e[e["definition_version"] == version].tail(MAX_DENOMINATOR_CANDIDATES)
    return {
        "definition_version": version,
        "tests_since_reset": since,
        "tests_total": total,
        "next_margin": multiple_testing.required_margin(since + 1, ctx.settings.thresholds["gate"]),
        "holdout_used": used,
        "holdout_budget": int(ctx.settings.budgets["holdout"]["max_gate_evaluations_per_definition"]),
        "candidates": [
            {
                "ref": str(r["candidate_ref"]),
                "auc": None if pd.isna(r["val_auc"]) else float(r["val_auc"]),
                "passed": None if pd.isna(r["passed_validation"]) else bool(r["passed_validation"]),
                "ts": _iso(r["ts"]),
            }
            for r in e.to_dict("records")
        ],
    }


# ---- entry point ----------------------------------------------------------------------------------------------
def newest_challenger(ctx: EvidenceContext) -> str | None:
    """Model key of the latest `candidate:*` evaluation under the active definition."""
    e = ctx.evaluations
    e = e[(e["definition_version"] == ctx.active_version) & e["candidate_ref"].astype(str).str.startswith("candidate:")]
    if e.empty:
        return None
    ref = str(e.sort_values("ts", kind="stable")["candidate_ref"].iloc[-1])
    return f"{registry_io.candidate_model_name()}/{ref.split(':', 1)[1]}"


def compute(ctx: EvidenceContext) -> pd.DataFrame:
    bench = ctx.current_benchmark_rows()
    serving = registry_sync.serving_version(ctx.registry)
    serving_key = serving.key if serving else None
    challenger_key = newest_challenger(ctx)
    primary_rows = bench[bench["benchmark_key"] == ctx.primary.key] if len(bench) else bench
    best = ledger.best_known(primary_rows, ctx.primary.key, ctx.cfg.reference.key) if len(primary_rows) else None
    keys = {k for k in (serving_key, challenger_key, None if best is None else str(best["model_key"])) if k}
    thresholds = ctx.settings.thresholds
    gr = {k: guardrails(ctx.eval_metrics, refs_for_key(k, ctx.registry), thresholds) for k in keys}
    result = decide(
        bench=bench,
        primary_key=ctx.primary.key,
        reference_key=ctx.cfg.reference.key,
        level=ctx.cfg.bootstrap.level,
        serving_key=serving_key,
        challenger_key=challenger_key,
        challenger_label=None if challenger_key is None else f"v{ledger.split_model_key(challenger_key)[1]}",
        guardrails_by_key=gr,
    )
    lift = result["lift"]
    if not result["guardrails"]:  # nothing to report on: still publish the limits, with unknown values
        result["guardrails"] = guardrails(ctx.eval_metrics, [], thresholds)
    row = {
        "computed_at": ctx.computed_at,
        "run_id": ctx.run_id,
        "active_definition": ctx.active_version,
        "primary_benchmark": ctx.primary.key,
        **{
            k: result[k]
            for k in (
                "verdict_code",
                "title",
                "detail",
                "best_known_key",
                "best_known_label",
                "newest_challenger_key",
                "newest_challenger_label",
                "serving_key",
            )
        },
        "lift_estimate": None if lift is None else lift.value,
        "lift_lo": None if lift is None else lift.lo,
        "lift_hi": None if lift is None else lift.hi,
        "guardrails_json": _dumps(result["guardrails"]),
        "denominator_json": _dumps(denominator(ctx)),
    }
    ctx.log(f"verdict: {row['verdict_code']} - {row['title']}")
    return schemas.conform("improvement_ledger", pd.DataFrame([row]))
