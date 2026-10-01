"""The decision log: every decision once, with the versions that made it.

ops.decisions           one row per decision_id (append-only Delta table): outcome, PD, band, reason codes, version
                        vector, shadow score, fallback, latency, source. No applicant inputs: this is the analytic
                        copy the console and monitoring read.
curated.decision_inputs the application as submitted and the cash-flow features as served, per decision_id
                        (applicant-level; agents and the console cannot read curated).
Rows come from the caller that received the response (synthetic traffic, load and parity checks) and, for calls
made by anyone else, from the endpoint's inference table (`reconcile`). Writing twice is harmless: decision ids are
deterministic and deduplicated.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from lau.store import get_store

TEST_PREFIXES = ("lt-", "parity-")  # load-test and parity-check requests: logged, excluded from analytics
# Explicit types: a batch where a column is empty (no shadow model yet, no fallback) must not create a text column.
FLOAT_COLUMNS = ("probability_of_default", "shadow_probability_of_default", "latency_ms", "client_latency_ms")
BOOL_COLUMNS = ("reasons_missing", "fallback_used", "is_test")


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _str(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return str(v)


def decision_row(resp: dict, source: str, client_latency_ms: float | None = None) -> dict:
    versions = json.loads(resp.get("versions_json") or "{}")
    shadow = json.loads(resp["shadow_json"]) if _str(resp.get("shadow_json")) else None
    reasons = json.loads(resp.get("reasons_json") or "[]")
    rid = str(resp["request_id"])
    return {
        "decision_id": str(resp["decision_id"]),
        "request_id": rid,
        "application_id": str(resp["application_id"]),
        "decision": str(resp["decision"]),
        "path": str(resp["path"]),
        "probability_of_default": _num(resp.get("probability_of_default")),
        "risk_band": _str(resp.get("risk_band")),
        "reason_codes": ",".join(r["code"] for r in reasons),
        "reasons_json": json.dumps(reasons),
        "reasons_missing": bool(resp.get("reasons_missing")),
        "unmapped_reasons": int(sum(1 for r in reasons if not r.get("mapped", True))),
        "model_version": _str(versions.get("model_version")),
        "definition_version": _str(versions.get("definition_version")),
        "policy_version": _str(versions.get("policy_version")),
        "build_id": _str(versions.get("build_id")),
        "code_version": _str(versions.get("code_version")),
        "shadow_model_version": _str(shadow.get("model_version")) if shadow else None,
        "shadow_probability_of_default": _num(shadow.get("probability_of_default")) if shadow else None,
        "shadow_decision": _str(shadow.get("decision")) if shadow else None,
        "fallback_used": bool(resp.get("fallback_used")),
        "fallback_reason": _str(resp.get("fallback_reason")),
        "latency_ms": _num(resp.get("latency_ms")),
        "client_latency_ms": _num(client_latency_ms),
        "decision_date": _str(resp.get("decision_date")),
        "decided_at": pd.Timestamp(resp["decided_at"]).tz_convert("UTC").tz_localize(None)
        if pd.Timestamp(resp["decided_at"]).tzinfo
        else pd.Timestamp(resp["decided_at"]),
        "payload_hash": _str(resp.get("payload_hash")),
        "is_test": rid.startswith(TEST_PREFIXES),
        "source": source,
        "logged_at": datetime.now(UTC).replace(tzinfo=None),
    }


def input_row(resp: dict, request: dict | None) -> dict:
    return {
        "decision_id": str(resp["decision_id"]),
        "request_id": str(resp["request_id"]),
        "application_id": str(resp["application_id"]),
        "decision_date": _str(resp.get("decision_date")),
        "application_json": _str((request or {}).get("application_json")),
        "n_transactions": len(json.loads((request or {}).get("transactions_json") or "[]")),
        "cashflow_json": _str(resp.get("cashflow_json")),
        "payload_hash": _str(resp.get("payload_hash")),
    }


def typed(df: pd.DataFrame) -> pd.DataFrame:
    for c in FLOAT_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    for c in BOOL_COLUMNS:
        df[c] = df[c].fillna(False).astype(bool)
    df["unmapped_reasons"] = df["unmapped_reasons"].astype("int64")
    return df


def _existing(ids: list[str]) -> set[str]:
    st = get_store("harness")
    if not ids or not st.table_exists("ops", "decisions"):
        return set()
    found: set[str] = set()
    for i in range(0, len(ids), 500):
        chunk = ", ".join("'" + x.replace("'", "''") + "'" for x in ids[i : i + 500])
        df = st.query(f"SELECT decision_id FROM {st.fq('ops', 'decisions')} WHERE decision_id IN ({chunk})")
        found |= set(df["decision_id"].astype(str))
    return found


def _ensure_append_only(st) -> None:
    if st.backend != "local":
        st.execute(f"ALTER TABLE {st.fq('ops', 'decisions')} SET TBLPROPERTIES ('delta.appendOnly' = 'true')")


def record(
    responses: list[dict],
    requests: list[dict] | None = None,
    source: str = "inprocess",
    client_latency_ms: list[float | None] | None = None,
) -> int:
    """Append decisions not logged yet (and their inputs). Returns how many were new."""
    if not responses:
        return 0
    by_request = {str(r["request_id"]): r for r in requests or []}
    seen = _existing([str(r["decision_id"]) for r in responses])
    rows, inputs = [], []
    for i, resp in enumerate(responses):
        did = str(resp["decision_id"])
        if did in seen:
            continue
        seen.add(did)
        lat = client_latency_ms[i] if client_latency_ms else None
        rows.append(decision_row(resp, source, lat))
        inputs.append(input_row(resp, by_request.get(str(resp["request_id"]))))
    if not rows:
        return 0
    st = get_store("harness")
    created = not st.table_exists("ops", "decisions")
    st.write_df("ops", "decisions", typed(pd.DataFrame(rows)), mode="append")
    if created:
        _ensure_append_only(st)
    st.write_df("curated", "decision_inputs", pd.DataFrame(inputs), mode="append")
    return len(rows)


# ---- the endpoint's own record ---------------------------------------------------------------------------------------
def inference_table() -> str:
    from lau.settings import get_settings

    s = get_settings()
    return s.fq("ops", f"{s.decisioning['endpoint']['inference_table_prefix']}_payload")


def parse_inference_rows(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """(responses, requests) from inference-table rows (dataframe_records / dataframe_split requests)."""
    responses, requests = [], []
    for row in df.to_dict("records"):
        if int(row.get("status_code") or 0) != 200 or not row.get("response"):
            continue
        body = json.loads(row["request"] or "{}")
        if "dataframe_records" in body:
            reqs = body["dataframe_records"]
        elif "dataframe_split" in body:
            split = body["dataframe_split"]
            reqs = [dict(zip(split["columns"], values, strict=True)) for values in split["data"]]
        else:
            reqs = []
        preds = json.loads(row["response"]).get("predictions") or []
        responses += preds
        requests += reqs
    return responses, requests


def reconcile(days: int = 3, log=print) -> dict:
    """Log decisions the endpoint returned to anyone (its inference table) that no caller has logged yet."""
    st = get_store("harness")
    from lau.settings import get_settings

    s = get_settings()
    table = f"{s.decisioning['endpoint']['inference_table_prefix']}_payload"
    if s.project.backend == "local" or not st.table_exists("ops", table):
        return {"reconciled": 0, "reason": "no inference table (endpoint not created)"}
    df = st.query(
        f"SELECT status_code, request, response FROM {inference_table()} "
        f"WHERE request_date >= date_sub(current_date(), {int(days)})"
    )
    responses, requests = parse_inference_rows(df)
    n = record(responses, requests, source="endpoint-log")
    log(f"reconciled {n} decision(s) from the endpoint's inference table ({len(responses)} seen)")
    return {"reconciled": n, "seen": len(responses)}
