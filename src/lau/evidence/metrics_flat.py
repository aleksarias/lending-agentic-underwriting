"""Flatten `ops.evaluations.result_json` into one (metric, value) row per number: `ops.evaluation_metrics`.

The console and the verdict's guardrail histories read the flat table (cheap to chart, no JSON parsing in SQL). Only
the headline numbers are kept, not the per-decile or per-segment detail that stays in `result_json`.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable

import pandas as pd

COLUMNS = ["eval_id", "candidate_ref", "definition_version", "ts", "metric", "value"]
TOP_LEVEL = ("thin_file_auc", "score_psi_train_val", "required_margin", "n_tests")


def _number(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v) if math.isfinite(v) else None


def flatten_result(result: dict) -> dict[str, float]:
    """validation.*, checks.* (1.0/0.0), fairness.min_air, reason-code coverage and the top-level headline numbers."""
    out: dict[str, float] = {}

    def put(name: str, v) -> None:
        x = _number(v)
        if x is not None:
            out[name] = x

    for k, v in (result.get("validation") or {}).items():
        put(f"validation.{k}", v)
    for k, v in (result.get("checks") or {}).items():
        if v is not None:
            out[f"checks.{k}"] = 1.0 if v else 0.0
    put("fairness.min_air", (result.get("fairness") or {}).get("min_air"))
    put("reason_code_quality.coverage_any", (result.get("reason_code_quality") or {}).get("coverage_any"))
    for k in TOP_LEVEL:
        put(k, result.get(k))
    return out


def flatten_evaluations(evals: pd.DataFrame, log: Callable[[str], None] | None = None) -> pd.DataFrame:
    """One row per numeric value of every evaluation in `ops.evaluations` (oldest first)."""
    rows: list[dict] = []
    bad = 0
    records = evals.sort_values("ts", kind="stable").to_dict("records") if len(evals) else []
    for r in records:
        try:
            values = flatten_result(json.loads(r["result_json"]))
        except (TypeError, ValueError):
            bad += 1
            continue
        rows.extend(
            {
                "eval_id": r["eval_id"],
                "candidate_ref": r["candidate_ref"],
                "definition_version": r["definition_version"],
                "ts": r["ts"],
                "metric": metric,
                "value": value,
            }
            for metric, value in values.items()
        )
    if bad and log:
        log(f"  {bad} evaluation(s) had unreadable result_json and were skipped")
    return pd.DataFrame(rows, columns=COLUMNS)


def compute(ctx) -> pd.DataFrame:
    return ctx.eval_metrics
