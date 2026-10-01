"""The decision engine: application + bank-statement lines -> decision, PD, band, reasons, versions.

Pure logic (no MLflow, no Databricks) shared by the served decision model, the in-process transport and the tests:
  1. knock-out rules on application fields (no model consulted)
  2. cash-flow features from the submitted statement lines, computed by the training code itself: the curate
     stage's SQL (`cashflow.monthly_sql`, run here on DuckDB) and `summarize_monthly`, so serving cannot drift
  3. PD from the serving champion within a time budget; band and approve / refer / decline under the policy
  4. principal reasons from the model's own contributions, mapped to adverse-action statements
  5. the legacy policy when no model is serving, and as the fallback when the model fails or runs out of time
Decision ids are deterministic in (request id, payload, model, policy): a retried request gets the same id.
"""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd

from lau.decision import reasons as R

# Model scoring runs on this pool so a slow model can be abandoned at the time budget (the thread finishes later).
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lau-pd")
TXN_FIELDS = ("txn_date", "amount", "balance_after", "category")


def _day(value: Any) -> date:
    if value is None or value == "":
        return datetime.now(UTC).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def payload_hash(request: dict) -> str:
    body = {k: request.get(k) for k in ("application", "transactions", "decision_date")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _monthly(tx: pd.DataFrame, months: int) -> pd.DataFrame:
    """The curate stage's monthly aggregation (same SQL text, including the anti-leakage guard) on DuckDB."""
    import duckdb

    from lau.synth.cashflow import monthly_sql

    con = duckdb.connect()
    try:
        con.execute("SET threads TO 1")  # one summation order: the same request always gets identical features
        con.register("submitted_transactions", tx)
        return con.execute(monthly_sql("submitted_transactions", months)).df()
    finally:
        con.close()


def request_frame(requests: list[dict], months_history: int = 6) -> pd.DataFrame:
    """One row per request: the application as submitted plus cf_* features recomputed from its statement lines.

    Submitted cf_* values are dropped (never trusted). Statement lines are dated relative to the request's
    decision date, so only lines strictly before it count, exactly like training.
    """
    from lau.synth.cashflow import CASHFLOW_FEATURES, summarize_monthly

    apps, lines = [], []
    for r in requests:
        rid = str(r["request_id"])
        app = {k: v for k, v in (r.get("application") or {}).items() if not str(k).startswith("cf_")}
        app["application_id"] = str(app.get("application_id") or rid)
        app["_request_id"] = rid
        apps.append(app)
        day = _day(r.get("decision_date"))
        for t in r.get("transactions") or []:
            d = _day(t["txn_date"])
            lines.append(
                {
                    "application_id": rid,  # grouped per request, so two requests never share statements
                    "txn_date": d,
                    "days_before_decision": (day - d).days,
                    "amount": float(t["amount"]),
                    "balance_after": float(t["balance_after"]),
                    "category": str(t.get("category") or ""),
                }
            )
    frame = pd.DataFrame(apps)
    if lines:
        monthly = _monthly(pd.DataFrame(lines), months_history)
        if len(monthly):
            stated = (
                pd.to_numeric(frame.set_index("_request_id")["annual_income"], errors="coerce")
                if "annual_income" in frame
                else pd.Series(dtype=float)
            )
            cf = summarize_monthly(monthly, stated).rename(columns={"application_id": "_request_id"})
            frame = frame.merge(cf, on="_request_id", how="left")
    for c in CASHFLOW_FEATURES:
        if c not in frame:
            frame[c] = np.nan  # no statements: missing, handled by the model like any missing input
    return frame


def band_of(pd_value: float, bands: dict[str, float]) -> str:
    for name, upper in bands.items():
        if pd_value <= upper:
            return name
    return list(bands)[-1]


def _statement(feature: str, lib: dict | None) -> dict:
    code, text = R.statement_for(feature, lib)
    return {"code": code, "statement": text, "feature": feature, "mapped": code != R.UNMAPPED}


def _number(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


def knockout(row: pd.Series, policy: dict, lib: dict | None = None) -> dict | None:
    ko = policy.get("knockouts") or {}
    dti = _number(row.get("dti"))
    if ko.get("max_dti") is not None and dti is not None and dti > ko["max_dti"]:
        return _statement("dti", lib)
    score = _number(row.get("bureau_score"))
    if ko.get("min_bureau_score") is not None and score is not None and score < ko["min_bureau_score"]:
        return _statement("bureau_score", lib)
    return None


def model_decision(p: float, policy: dict) -> str:
    d = policy["decision"]
    if p <= d["approve_max_pd"]:
        return "approve"
    if p <= d["refer_max_pd"]:
        return "refer"
    return "decline"


def decision_id(request_id: str, payload: str, versions: dict) -> str:
    key = f"{request_id}|{payload}|{versions.get('model_version')}|{versions.get('policy_version')}"
    return "dec-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _score(model: Any, frame: pd.DataFrame, timeout_ms: int | None) -> np.ndarray:
    if not timeout_ms:
        return np.asarray(model.predict_pd(frame), dtype=float)
    return np.asarray(_POOL.submit(model.predict_pd, frame).result(timeout=timeout_ms / 1000), dtype=float)


def decide(
    requests: list[dict],
    serving: Any | None,
    policy: dict,
    versions: dict,
    *,
    shadow: Any | None = None,
    reasons_lib: dict | None = None,
    months_history: int = 6,
    timeout_ms: int | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Decide a batch; one record per request, in order. `serving`/`shadow` are PDModel-like or None.

    A request id repeated within the batch is decided once and returned for each occurrence.
    """
    t0 = time.perf_counter()
    now = now or datetime.now(UTC)
    unique = list({str(r["request_id"]): r for r in reversed(requests)}.values())[::-1]  # first occurrence wins
    frame = request_frame(unique, months_history)
    top_n = int(policy.get("reason_codes", 4))

    pd_serving, failure = None, None
    if serving is not None:
        try:
            pd_serving = _score(serving, frame, timeout_ms)
        except FutureTimeout:
            failure = f"timeout: no score within {timeout_ms} ms"
        except Exception as e:  # noqa: BLE001 - the legacy policy decides instead, and the record says why
            failure = f"{type(e).__name__}: {str(e)[:200]}"
    pd_shadow = None
    if shadow is not None:
        try:
            pd_shadow = _score(shadow, frame, timeout_ms)
        except Exception:  # noqa: BLE001 - shadow scores are informational; their absence never affects a decision
            pd_shadow = None

    contributions: dict[int, dict[str, float]] = {}
    if pd_serving is not None:
        adverse = [i for i in range(len(frame)) if model_decision(pd_serving[i], policy) != "approve"]
        if adverse:
            try:
                c = serving.contributions(frame.iloc[adverse])
                for pos, i in enumerate(adverse):
                    contributions[i] = {str(k): float(v) for k, v in c.iloc[pos].items()}
            except Exception:  # noqa: BLE001 - flagged per decision below (reasons_missing), never silently empty
                contributions = {}

    from lau.synth.cashflow import CASHFLOW_FEATURES

    legacy_min = float(policy["legacy"]["min_score"])
    decided: dict[str, dict] = {}
    for i, req in enumerate(unique):
        row = frame.iloc[i]
        rid = str(req["request_id"])
        payload = payload_hash(req)
        record: dict[str, Any] = {
            "decision_id": decision_id(rid, payload, versions),
            "request_id": rid,
            "application_id": str(row["application_id"]),
            "payload_hash": payload,
            "decision_date": _day(req.get("decision_date")).isoformat(),
            "decided_at": now.isoformat(),
            "versions": versions,
            "fallback_used": failure is not None,
            "fallback_reason": failure,
            "reasons_missing": False,
            "shadow": None,
            "cashflow_features": {c: _number(row.get(c)) for c in CASHFLOW_FEATURES},
        }
        ko = knockout(row, policy, reasons_lib)
        if ko is not None:
            record.update(
                decision="decline", path="knockout", probability_of_default=None, risk_band=None, reasons=[ko]
            )
        elif pd_serving is not None:
            p = float(pd_serving[i])
            outcome = model_decision(p, policy)
            why = R.principal_reasons(contributions.get(i, {}), top_n, reasons_lib) if outcome != "approve" else []
            record.update(
                decision=outcome,
                path="model",
                probability_of_default=round(p, 6),
                risk_band=band_of(p, policy["bands"]),
                reasons=why,
                reasons_missing=outcome != "approve" and not why,
            )
        else:
            score = _number(row.get("legacy_score"))
            ok = score is not None and score >= legacy_min
            record.update(
                decision="approve" if ok else "decline",
                path="legacy",
                probability_of_default=None,
                risk_band=None,
                reasons=[] if ok else [_statement("legacy_score", reasons_lib)],
            )
        if pd_shadow is not None:
            sp = float(pd_shadow[i])
            record["shadow"] = {
                "model_version": versions.get("shadow_model_version"),
                "probability_of_default": round(sp, 6),
                "decision": model_decision(sp, policy),
                "risk_band": band_of(sp, policy["bands"]),
            }
        decided[rid] = record
    per_request = round((time.perf_counter() - t0) * 1000 / max(len(unique), 1), 2)
    for r in decided.values():
        r["latency_ms"] = per_request
    return [decided[str(r["request_id"])] for r in requests]
