"""The benchmark ledger (ops.benchmark_results): every model re-scored under the same frozen benchmark definitions.

Only the latest run is shown as the matrix; earlier runs feed the "over time" views through the improvement ledger.
"""

from __future__ import annotations

import re

import pandas as pd

from lau.console import deps
from lau.console.services import config, models
from lau.console.services import definitions as defs
from lau.console.util import boolean, integer, iso, num, read_table, short, table_exists, text, ttl_cache

_KEY_RE = re.compile(r"^dpd(?P<dpd>\d+)_(?P<timing>ever|eow)_(?P<window>\d+)m$")


@ttl_cache(30)
def latest_run() -> pd.DataFrame:
    """Rows of the newest benchmark run (empty when the evidence job has never run)."""
    st = deps.ui_store()
    if not table_exists(st, "ops", "benchmark_results"):
        return pd.DataFrame()
    t = st.fq("ops", "benchmark_results")
    return read_table(
        st,
        "ops",
        "benchmark_results",
        where=f"run_id = (SELECT run_id FROM {t} ORDER BY computed_at DESC LIMIT 1)",
        ts=["computed_at"],
    )


def benchmark_label(key: str, dpd: int) -> str:
    m = _KEY_RE.match(key)
    if not m:
        return f"{dpd} DPD"
    timing = "ever" if m["timing"] == "ever" else "at end of window"
    return f"{m['dpd']} DPD {timing} / {m['window']} months"


def definitions_of(df: pd.DataFrame) -> list[dict]:
    auc = df[(df["metric"] == "auc") & (df["model_key"] == models.REFERENCE_KEY)]
    if auc.empty:
        auc = df[df["metric"] == "auc"].drop_duplicates("benchmark_key")
    out = []
    for r in auc.drop_duplicates("benchmark_key").to_dict("records"):
        dpd = integer(r.get("benchmark_dpd")) or 0
        out.append(
            {
                "key": str(r["benchmark_key"]),
                "label": benchmark_label(str(r["benchmark_key"]), dpd),
                "dpd": dpd,
                "version": str(text(r.get("benchmark_version")) or ""),
                "n_defaults": integer(r.get("n_defaults")) or 0,
            }
        )
    return sorted(out, key=lambda d: d["dpd"])


def trained_under(r: dict) -> str:
    if r.get("model_key") == models.REFERENCE_KEY:
        return "—"
    ref = defs.definition_ref(text(r.get("trained_definition")))
    head = ref["summary"] if ref else (short(text(r.get("trained_definition"))) or "unknown definition")
    dv = short(text(r.get("trained_data_version")))
    return f"{head}, data {dv}" if dv else head


def model_ref_of(r: dict) -> dict:
    return (
        models.ref_from_key(
            str(r["model_key"]),
            text(r.get("model_label")),
            text(r.get("model_kind")),
            text(r.get("trained_definition")),
        )
        or models.reference_ref()
    )


def _rows_by_model(df: pd.DataFrame) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in df.to_dict("records"):
        out.setdefault(str(r["model_key"]), []).append(r)
    return out


def benchmark_row(key: str, rows: list[dict], primary: str) -> dict:
    first = rows[0]
    metrics, is_best, bad_rate = {}, {}, None
    for r in rows:
        bench = str(r["benchmark_key"])
        if r["metric"] == "auc":
            metrics[bench] = {"auc": num(r["value"]) or 0.0, "ci_lo": num(r.get("ci_lo")), "ci_hi": num(r.get("ci_hi"))}
            is_best[bench] = bool(boolean(r.get("is_best")))
        elif r["metric"] == "bad_rate_at_fixed_approval" and bench == primary:
            bad_rate = num(r["value"])
    return {
        "model": model_ref_of(first),
        "trained_under": trained_under(first),
        "data_version": text(first.get("trained_data_version")),
        "metrics": metrics,
        "bad_rate_at_fixed_approval": bad_rate,
        "is_best": is_best,
        "selected_on_window": bool(boolean(first.get("selected_on_window"))),
    }


def row_for_key(key: str | None) -> dict | None:
    df = latest_run()
    if df.empty or not key:
        return None
    mine = df[df["model_key"] == key]
    return None if mine.empty else benchmark_row(key, mine.to_dict("records"), primary_key(df))


def primary_key(df: pd.DataFrame | None = None) -> str:
    key = config.primary_benchmark_key()
    if key:
        return key
    df = latest_run() if df is None else df
    return str(df["benchmark_key"].iloc[0]) if len(df) else ""


def matrix() -> dict | None:
    df = latest_run()
    if df.empty:
        return None
    primary = primary_key(df)
    first = df.iloc[0]
    ref_auc = df[(df["metric"] == "auc") & (df["benchmark_key"] == primary)]
    n_loans = int(ref_auc["n"].max()) if len(ref_auc) else 0
    rows = [benchmark_row(k, rs, primary) for k, rs in _rows_by_model(df).items()]

    def sort_key(row: dict) -> tuple:
        cell = row["metrics"].get(primary) or {}
        return (row["model"]["kind"] != "reference", cell.get("auc") or 0.0)

    rows.sort(key=sort_key, reverse=True)
    return {
        "computed_at": iso(df["computed_at"].max()),
        "window": {
            "start": str(first.get("window_start") or ""),
            "end": str(first.get("window_end") or ""),
            "n_loans": n_loans,
            "policy": str(first.get("window_policy") or ""),
        },
        "fixed_approval_rate": config.fixed_approval_rate(),
        "definitions": definitions_of(df),
        "primary_definition": primary,
        "rows": rows,
    }


def diffs(metric: str) -> list[dict]:
    """DiffRows for `auc_minus_reference` or `auc_minus_best_known` (latest run, every benchmark)."""
    df = latest_run()
    if df.empty:
        return []
    sub = df[(df["metric"] == metric) & df["versus_key"].notna()]
    labels = {str(r["model_key"]): r for r in df[df["metric"] == "auc"].to_dict("records")}
    out = []
    for r in sub.to_dict("records"):
        est = num(r["value"])
        if est is None:
            continue
        versus = labels.get(str(r["versus_key"]))
        out.append(
            {
                "model": model_ref_of(r),
                "versus": model_ref_of(versus) if versus else models.ref_from_key(str(r["versus_key"])),
                "definition_key": str(r["benchmark_key"]),
                "diff": {
                    "estimate": est,
                    "lo": num(r.get("ci_lo")) if num(r.get("ci_lo")) is not None else est,
                    "hi": num(r.get("ci_hi")) if num(r.get("ci_hi")) is not None else est,
                    "n": integer(r.get("n")),
                },
            }
        )
    return out


def beats_best_known(key: str, best_key: str | None) -> bool | None:
    """True when `key` is the best known model on the primary benchmark or beats it (CI above zero)."""
    df = latest_run()
    if df.empty or not key:
        return None
    if best_key and key == best_key:
        return True
    primary = primary_key(df)
    hit = df[(df["model_key"] == key) & (df["metric"] == "auc_minus_best_known") & (df["benchmark_key"] == primary)]
    if hit.empty:
        return None
    lo = num(hit["ci_lo"].iloc[0])
    return bool(lo is not None and lo > 0)
