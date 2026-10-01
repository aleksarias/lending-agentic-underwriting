"""Read side of the evidence tables: the latest benchmark run, the best known model, the latest data version.

Deliberately light (pandas + SQL only, no MLflow) so that the harness can import it inside `evaluate_model`.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


def _q(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def latest_data_version(store) -> dict | None:
    """{data_version, as_of_month, created_at} of the newest raw data load, or None."""
    if not store.table_exists("ops", "data_version"):
        return None
    df = store.query(
        f"SELECT data_version, as_of_month, created_at FROM {store.fq('ops', 'data_version')} "
        "ORDER BY created_at DESC LIMIT 1"
    )
    return None if df.empty else df.iloc[0].to_dict()


def latest_benchmark_run_id(store) -> str | None:
    if not store.table_exists("ops", "benchmark_results"):
        return None
    df = store.query(f"SELECT run_id FROM {store.fq('ops', 'benchmark_results')} ORDER BY computed_at DESC LIMIT 1")
    return None if df.empty else str(df["run_id"].iloc[0])


def latest_benchmark_rows(store, metric: str | None = None, benchmark_key: str | None = None) -> pd.DataFrame:
    """Rows of the newest `ops.benchmark_results` run (optionally one metric / one benchmark); empty if none."""
    run_id = latest_benchmark_run_id(store)
    if run_id is None:
        return pd.DataFrame()
    where = [f"run_id = {_q(run_id)}"]
    if metric:
        where.append(f"metric = {_q(metric)}")
    if benchmark_key:
        where.append(f"benchmark_key = {_q(benchmark_key)}")
    return store.query(f"SELECT * FROM {store.fq('ops', 'benchmark_results')} WHERE {' AND '.join(where)}")


def best_known(
    rows: pd.DataFrame, benchmark_key: str, reference_key: str, exclude: Iterable[str] = ()
) -> pd.Series | None:
    """The best known model under a benchmark: highest AUC, excluding the frozen reference and `exclude` keys.

    Ties go to the row that comes first in the ledger (older candidates first, then production copies).
    """
    if rows.empty:
        return None
    sub = rows[(rows["metric"] == "auc") & (rows["benchmark_key"] == benchmark_key) & rows["value"].notna()]
    sub = sub[(sub["model_key"] != reference_key) & ~sub["model_key"].isin(list(exclude))]
    if sub.empty:
        return None
    return sub.sort_values("value", ascending=False, kind="stable").iloc[0]


def split_model_key(model_key: str) -> tuple[str, str]:
    """`<registered model name>/<version>` -> (name, version)."""
    name, _, version = model_key.rpartition("/")
    return name, version
