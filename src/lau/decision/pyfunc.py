"""The decision model: one MLflow pyfunc that holds everything a decision needs.

It embeds the serving champion (or none: the legacy policy decides), an optional shadow model (a promoted champion
waiting for its rollout), the ACTIVE approved policy, the reason statements and the version vector. Nothing is read
from config or tables at request time, so a served version always decides the same way.

Request rows (all strings; nested values are JSON):
  request_id         caller's idempotency key
  application_json   the application as submitted (no cf_* features: they are computed here)
  transactions_json  bank-statement lines [{txn_date, amount, balance_after, category}], optional
  decision_date      ISO date the decision is made for (default: today), optional
Response rows: one per request, see OUTPUT_COLUMNS.
"""

from __future__ import annotations

import json
import os
from typing import Any

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow.pyfunc  # noqa: E402
import pandas as pd  # noqa: E402

from lau.decision import engine  # noqa: E402

INPUT_COLUMNS = {"request_id": True, "application_json": True, "transactions_json": False, "decision_date": False}
OUTPUT_COLUMNS = {
    "decision_id": "string",
    "request_id": "string",
    "application_id": "string",
    "decision": "string",
    "path": "string",
    "probability_of_default": "double",
    "risk_band": "string",
    "reasons_json": "string",
    "versions_json": "string",
    "fallback_used": "boolean",
    "fallback_reason": "string",
    "reasons_missing": "boolean",
    "shadow_json": "string",
    "cashflow_json": "string",
    "payload_hash": "string",
    "decision_date": "string",
    "decided_at": "string",
    "latency_ms": "double",
}


def parse_request(row: dict) -> dict:
    def loads(value: Any, default: Any) -> Any:
        if value is None or (isinstance(value, float) and value != value) or value == "":
            return default
        return json.loads(value) if isinstance(value, str) else value

    return {
        "request_id": str(row["request_id"]),
        "application": loads(row.get("application_json"), {}),
        "transactions": loads(row.get("transactions_json"), []),
        "decision_date": row.get("decision_date") or None,
    }


def to_request_row(request: dict) -> dict:
    """The inverse of parse_request: what a client sends (used by the traffic job and the tests)."""
    return {
        "request_id": str(request["request_id"]),
        "application_json": json.dumps(request.get("application") or {}, default=str),
        "transactions_json": json.dumps(request.get("transactions") or [], default=str),
        "decision_date": str(request.get("decision_date") or ""),
    }


def to_response_row(record: dict) -> dict:
    return {
        "decision_id": record["decision_id"],
        "request_id": record["request_id"],
        "application_id": record["application_id"],
        "decision": record["decision"],
        "path": record["path"],
        "probability_of_default": record["probability_of_default"],
        "risk_band": record["risk_band"],
        "reasons_json": json.dumps(record["reasons"]),
        "versions_json": json.dumps(record["versions"], sort_keys=True),
        "fallback_used": bool(record["fallback_used"]),
        "fallback_reason": record["fallback_reason"],
        "reasons_missing": bool(record["reasons_missing"]),
        "shadow_json": json.dumps(record["shadow"]) if record["shadow"] else None,
        "cashflow_json": json.dumps(record["cashflow_features"]),
        "payload_hash": record["payload_hash"],
        "decision_date": record["decision_date"],
        "decided_at": record["decided_at"],
        "latency_ms": float(record["latency_ms"]),
    }


class DecisionModel(mlflow.pyfunc.PythonModel):
    def __init__(
        self,
        serving: Any | None = None,
        shadow: Any | None = None,
        policy: dict | None = None,
        reasons_lib: dict | None = None,
        versions: dict | None = None,
        months_history: int = 6,
        timeout_ms: int | None = 250,
    ) -> None:
        self.serving = serving
        self.shadow = shadow
        self.policy = policy or {}
        self.reasons_lib = reasons_lib or {}
        self.versions = versions or {}
        self.months_history = int(months_history)
        self.timeout_ms = timeout_ms

    def decide(self, requests: list[dict]) -> list[dict]:
        return engine.decide(
            requests,
            self.serving,
            self.policy,
            self.versions,
            shadow=self.shadow,
            reasons_lib=self.reasons_lib,
            months_history=self.months_history,
            timeout_ms=self.timeout_ms,
        )

    def predict(self, context, model_input: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
        requests = [parse_request(r) for r in model_input.to_dict("records")]
        rows = [to_response_row(r) for r in self.decide(requests)]
        return pd.DataFrame(rows, columns=list(OUTPUT_COLUMNS))


def signature():
    from mlflow.models import ModelSignature
    from mlflow.types.schema import ColSpec, Schema

    inputs = Schema([ColSpec("string", name, required=req) for name, req in INPUT_COLUMNS.items()])
    outputs = Schema([ColSpec(kind, name, required=False) for name, kind in OUTPUT_COLUMNS.items()])
    return ModelSignature(inputs=inputs, outputs=outputs)


def pip_requirements() -> list[str]:
    """Exact versions of everything the pickled models and the engine touch, so serving loads what was tested."""
    from importlib.metadata import version

    pinned = ["lightgbm", "xgboost", "scikit-learn", "pandas", "numpy", "duckdb", "sqlglot", "pyarrow", "pydantic"]
    return [f"{p}=={version(p)}" for p in pinned] + [f"pyyaml=={version('PyYAML')}", f"mlflow=={version('mlflow')}"]
