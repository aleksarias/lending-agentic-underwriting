"""Run the evidence steps in dependency order and write their `ops.*` tables.

    model_registry -> evaluation_metrics -> benchmark_results -> definition_sensitivity -> vintage_curves
    -> cashflow_cohorts -> proxy_scan -> production_evidence -> decision_fairness -> serving_parity
    -> policy_tradeoff -> readiness_evidence -> improvement_ledger
The three production steps read the decision log and the loan status feed; before either exists they are skipped.

Per-run tables are appended with one shared run_id and computed_at; `model_registry` and `evaluation_metrics` are
replaced each run. A step whose prerequisites are missing (no active definition, no data load) is skipped with a
message; any other failure is logged, the remaining steps still run, and `EvidenceRunError` is raised at the end so
a job never reports success for a partial refresh.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable

import pandas as pd

from lau import readiness
from lau.decision import tradeoff
from lau.evidence import benchmark, cohorts, metrics_flat, outcomes, proxies, registry_sync, schemas, verdict
from lau.evidence.config import BenchmarkConfig
from lau.evidence.context import EvidenceContext, EvidenceNotReadyError
from lau.feedback import fairness as decision_fairness
from lau.feedback import parity, production

STEPS: dict[str, Callable[[EvidenceContext], pd.DataFrame]] = {
    "model_registry": registry_sync.compute,
    "evaluation_metrics": metrics_flat.compute,
    "benchmark_results": benchmark.compute,
    "definition_sensitivity": outcomes.sensitivity,
    "vintage_curves": outcomes.vintage,
    "cashflow_cohorts": cohorts.compute,
    "proxy_scan": proxies.compute,
    "production_evidence": production.compute,
    "decision_fairness": decision_fairness.compute,
    "serving_parity": parity.compute,
    "policy_tradeoff": tradeoff.compute,
    "readiness_evidence": readiness.compute,
    "improvement_ledger": verdict.compute,
}
ALIASES = {
    "registry": "model_registry",
    "metrics": "evaluation_metrics",
    "benchmark": "benchmark_results",
    "sensitivity": "definition_sensitivity",
    "vintage": "vintage_curves",
    "cashflow": "cashflow_cohorts",
    "proxy": "proxy_scan",
    "proxies": "proxy_scan",
    "verdict": "improvement_ledger",
    "ledger": "improvement_ledger",
    "production": "production_evidence",
    "fairness": "decision_fairness",
    "parity": "serving_parity",
    "tradeoff": "policy_tradeoff",
    "what-if": "policy_tradeoff",
    "readiness": "readiness_evidence",
}


class EvidenceRunError(RuntimeError):
    """One or more steps failed; `counts` holds the tables that were written, `errors` the failures."""

    def __init__(self, counts: dict[str, int], errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{t}: {e}" for t, e in errors.items()))
        self.counts = counts
        self.errors = errors


def resolve_only(only: str | Iterable[str] | None) -> list[str]:
    """Table names (optionally `ops.`-prefixed, or a short alias such as `benchmark`) in canonical run order."""
    if only is None:
        return list(STEPS)
    names = only.split(",") if isinstance(only, str) else list(only)
    wanted = set()
    for raw in names:
        name = raw.strip().lower().removeprefix("ops.")
        if not name:
            continue
        name = ALIASES.get(name, name)
        if name not in STEPS:
            raise ValueError(f"unknown evidence step {raw!r}; choose from {sorted({*STEPS, *ALIASES})}")
        wanted.add(name)
    return [t for t in STEPS if t in wanted]


def write_table(ctx: EvidenceContext, table: str, df: pd.DataFrame) -> int:
    """Write one step's rows: append (per-run tables) or replace (registry, metrics). Returns the row count."""
    df = schemas.conform(table, df)
    if table in schemas.OVERWRITE_TABLES:
        if df.empty and not ctx.store.table_exists("ops", table):
            return 0
        ctx.store.write_df("ops", table, df, mode="overwrite")
    else:
        if df.empty:  # appending an empty frame would only pin the column types of a table nobody has filled yet
            return 0
        ctx.store.write_df("ops", table, df, mode="append")
    return len(df)


def run_all(
    log: Callable[[str], None] = print,
    only: str | Iterable[str] | None = None,
    *,
    store=None,
    cfg: BenchmarkConfig | None = None,
) -> dict[str, int]:
    """Run every evidence step (or just `only`), write the tables, and return {table: rows written}."""
    steps = resolve_only(only)
    ctx = EvidenceContext(store=store, log=log, cfg=cfg)
    log(f"evidence run {ctx.run_id} as the harness identity")
    counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for table in steps:
        t0 = time.monotonic()
        try:
            df = STEPS[table](ctx)
            counts[table] = write_table(ctx, table, df)
            if table == "benchmark_results" and counts[table]:
                ctx.benchmark_rows = df  # the verdict reads what was just written
        except EvidenceNotReadyError as e:
            counts[table] = 0
            log(f"  ops.{table}: skipped ({e})")
            continue
        except Exception as e:  # noqa: BLE001 - keep the other steps going; reported together at the end
            errors[table] = f"{type(e).__name__}: {e}"
            log(f"  ops.{table}: FAILED ({errors[table]})")
            continue
        log(f"  ops.{table}: {counts[table]:,} row(s) in {time.monotonic() - t0:.1f}s")
    if errors:
        raise EvidenceRunError(counts, errors)
    return counts
