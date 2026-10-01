"""Release checks for the decision API, recorded in ops.release_checks:

  parity    the served path (statement lines -> engine) produces the same cash-flow features and the same PD as the
            training path (curate stage -> curated.new_applications) for the same applications
  load      client-side latency of single-application requests at a fixed concurrency against config targets
            (p95/p99); the first (cold) request is reported separately
  rollback  what a rollback would restore (the previous serving model, or the legacy policy) loads and decides a
            sample correctly; nothing in production changes
Requests made by checks carry `parity-` / `lt-` request ids: they are logged but excluded from analytics.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.decision import engine, traffic
from lau.decision.pyfunc import to_request_row
from lau.settings import get_settings
from lau.store import get_store


def _record(check: str, passed: bool, details: dict, build_id: str | None) -> dict:
    row = {
        "check_id": f"{check}-{int(time.time())}",
        "check": check,
        "passed": bool(passed),
        "details_json": json.dumps(details, default=str),
        "build_id": build_id,
        "run_at": datetime.now(UTC).replace(tzinfo=None),
    }
    get_store("harness").write_df("ops", "release_checks", pd.DataFrame([row]), mode="append")
    return {"check": check, "passed": bool(passed), **details}


def _live_model():
    from lau.decision.build import load_live

    model = load_live()
    if model is None:
        raise traffic.NoDecisionModelError("no decision model is live: approve a policy, then `lau decision build`")
    return model


def parity(n: int = 200, log=print) -> dict:
    from lau.synth.cashflow import CASHFLOW_FEATURES

    st = get_store("harness")
    model = _live_model()
    raw = st.query(f"SELECT * FROM {st.fq('raw', 'new_applications_raw')} ORDER BY application_id LIMIT {int(n)}")
    ids = ", ".join(f"'{a}'" for a in raw["application_id"])
    tx = st.query(
        "SELECT application_id, txn_date, days_before_decision, amount, balance_after, category "
        f"FROM {st.fq('raw', 'bank_transactions')} WHERE application_id IN ({ids}) AND days_before_decision >= 1"
    )
    curated = st.query(f"SELECT * FROM {st.fq('curated', 'new_applications')} WHERE application_id IN ({ids})")
    curated = curated.set_index("application_id").loc[raw["application_id"]].reset_index()
    requests = traffic.build_requests(raw, tx, prefix="parity-")
    served = engine.request_frame(requests, model.months_history)

    feature_gaps = {}
    for c in CASHFLOW_FEATURES:
        a = pd.to_numeric(served[c], errors="coerce").to_numpy(float)
        b = pd.to_numeric(curated[c], errors="coerce").to_numpy(float)
        both_nan = np.isnan(a) & np.isnan(b)
        diff = np.where(both_nan, 0.0, np.abs(a - b))
        feature_gaps[c] = float(np.nanmax(np.where(np.isnan(diff), np.inf, diff))) if len(diff) else 0.0
    pd_gap = None
    if model.serving is not None:
        decided = model.decide(requests)
        served_pd = np.array([d["probability_of_default"] for d in decided if d["path"] == "model"], dtype=float)
        keep = [d["path"] == "model" for d in decided]
        trained_pd = np.round(model.serving.predict_pd(curated[keep]), 6) if any(keep) else np.array([])
        pd_gap = float(np.max(np.abs(served_pd - trained_pd))) if len(served_pd) else 0.0
    worst = max(feature_gaps.values()) if feature_gaps else 0.0
    passed = worst <= 1e-9 and (pd_gap is None or pd_gap <= 1e-6)
    details = {
        "n": len(raw),
        "max_feature_gap": worst,
        "feature_gaps": {k: v for k, v in feature_gaps.items() if v > 0},
        "max_pd_gap": pd_gap,
    }
    log(
        f"parity on {len(raw)} applications: max feature gap {worst:g}, max PD gap {pd_gap} "
        f"-> {'PASS' if passed else 'FAIL'}"
    )
    return _record("parity", passed, details, model.versions.get("build_id"))


def load(n: int = 300, concurrency: int = 4, kind: str = "auto", log=print) -> dict:
    from lau.decision import log as decision_log

    targets = get_settings().decisioning["targets"]
    via = traffic.transport(kind)
    apps, tx, _ = traffic.generate_month(traffic.current_month(), n + 1)
    requests = traffic.build_requests(apps, tx, prefix="lt-")
    rows = [to_request_row(r) for r in requests]

    t0 = time.perf_counter()
    first = via.decide([rows[0]])
    cold_ms = (time.perf_counter() - t0) * 1000

    def one(row: dict) -> tuple[float, list[dict] | None, str | None]:
        t = time.perf_counter()
        try:
            out = via.decide([row])
            return (time.perf_counter() - t) * 1000, out, None
        except Exception as e:  # noqa: BLE001 - counted as an error, the test goes on
            return (time.perf_counter() - t) * 1000, None, f"{type(e).__name__}: {str(e)[:120]}"

    t1 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        results = list(ex.map(one, rows[1:]))
    wall = time.perf_counter() - t1
    lat = np.array([r[0] for r in results if r[2] is None])
    errors = [r[2] for r in results if r[2] is not None]
    responses = first + [x for r in results if r[1] for x in r[1]]
    decision_log.record(responses, rows, source=via.name)
    p = {q: float(np.percentile(lat, q)) if len(lat) else None for q in (50, 95, 99)}
    fallback = float(np.mean([bool(r.get("fallback_used")) for r in responses])) if responses else None
    passed = not errors and p[95] is not None and p[95] <= targets["p95_ms"] and p[99] <= targets["p99_ms"]
    details = {
        "transport": via.name,
        "n": len(results),
        "concurrency": concurrency,
        "cold_start_ms": round(cold_ms, 1),
        "p50_ms": p[50],
        "p95_ms": p[95],
        "p99_ms": p[99],
        "targets": targets,
        "throughput_rps": round(len(results) / wall, 2) if wall else None,
        "errors": len(errors),
        "first_errors": errors[:3],
        "fallback_share": fallback,
    }
    log(
        f"load via {via.name}: p50 {p[50]:.0f} ms, p95 {p[95]:.0f} ms, p99 {p[99]:.0f} ms "
        f"(targets {targets['p95_ms']}/{targets['p99_ms']}), {len(errors)} errors, cold start {cold_ms:.0f} ms "
        f"-> {'PASS' if passed else 'FAIL'}"
        if len(lat)
        else f"load via {via.name}: every request failed ({errors[:1]})"
    )
    build_id = responses and json.loads(responses[0].get("versions_json") or "{}").get("build_id")
    return _record("load", passed, details, build_id or None)


def rollback(n: int = 100, log=print) -> dict:
    """Decide a sample with what a rollback would restore, in memory; production is untouched."""
    from lau.decision import rollout
    from lau.decision.pyfunc import DecisionModel
    from lau.modeling import registry_io

    model = _live_model()
    serving = rollout.in_state("serving")
    target = serving["previous_serving_version"] if serving else None
    t0 = time.perf_counter()
    previous = (
        registry_io.load_pd_model(f"models:/{registry_io.production_model_name()}/{target}", "harness")
        if target
        else None
    )
    restored = DecisionModel(
        serving=previous,
        policy=model.policy,
        reasons_lib=model.reasons_lib,
        versions={**model.versions, "model_version": target, "shadow_model_version": None},
        months_history=model.months_history,
        timeout_ms=model.timeout_ms,
    )
    apps, tx, _ = traffic.generate_month(traffic.current_month(), n)
    decided = restored.decide(traffic.build_requests(apps, tx, prefix="drill-"))
    seconds = round(time.perf_counter() - t0, 2)
    expected_path = {"model", "knockout"} if previous is not None else {"legacy", "knockout"}
    valid = all(d["decision"] in ("approve", "refer", "decline") and d["path"] in expected_path for d in decided)
    explained = all(d["reasons"] for d in decided if d["decision"] == "decline")
    passed = valid and explained
    details = {
        "restores": f"v{target}" if target else "legacy policy",
        "from_rollout": serving["rollout_id"] if serving else None,
        "basis": (
            f"rolling back {serving['rollout_id']} restores what served before it"
            if serving
            else "no rollout is serving: the drill proves the legacy policy, the last resort, decides correctly"
        ),
        "n": len(decided),
        "seconds_to_decide_with_restored": seconds,
        "all_declines_have_reasons": explained,
    }
    log(
        f"rollback drill: {details['restores']} decides {len(decided)} applications in {seconds}s "
        f"-> {'PASS' if passed else 'FAIL'}"
    )
    return _record("rollback", passed, details, model.versions.get("build_id"))
