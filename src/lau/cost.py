"""Cost guardrails: pre-run estimates, in-process metering, actuals from system.billing, and hard caps.

Databricks cost model (estimate): serverless SQL warehouse DBU/h (config) x expected busy minutes + the warehouse's
minimum billable window after the last query (auto_stop_mins). Local pandas/LightGBM compute is free.
Anthropic cost: per-agent priors (config/models.yaml) for estimates; actuals from ResultMessage.total_cost_usd.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from lau.settings import get_settings

_LOCK = threading.Lock()
_WAREHOUSE_SECONDS = 0.0


def record_warehouse_seconds(sec: float) -> None:
    global _WAREHOUSE_SECONDS
    with _LOCK:
        _WAREHOUSE_SECONDS += sec


def warehouse_seconds() -> float:
    return _WAREHOUSE_SECONDS


class BudgetExceededError(RuntimeError):
    pass


# Rough busy-minutes per stage on a 2X-Small warehouse at the default synthetic size (50k apps, ~1M perf rows).
STAGE_WAREHOUSE_MINUTES = {
    "ingest": 3.0,
    "curate": 1.5,
    "labels": 2.0,
    "splits": 1.0,
    "catalog": 1.5,
    "feature_registry_eval": 1.0,
    "baseline_retrain": 1.5,
    "harness_reference": 1.0,
    "monitoring_baseline": 0.5,
    "lessons": 0.0,
    "improvement_cycle": 6.0,
}


@dataclass
class CostEstimate:
    dbu: float = 0.0
    databricks_usd: float = 0.0
    anthropic_usd: float = 0.0
    lines: list[str] = field(default_factory=list)

    @property
    def total_usd(self) -> float:
        return self.databricks_usd + self.anthropic_usd

    def render(self) -> str:
        body = "\n".join(f"  - {ln}" for ln in self.lines)
        return (
            f"Estimated cost: {self.dbu:.2f} DBU (~${self.databricks_usd:.2f} Databricks) + "
            f"~${self.anthropic_usd:.2f} Anthropic = ~${self.total_usd:.2f}\n{body}"
        )


def _scale() -> float:
    s = get_settings()
    return max(0.2, s.synth.get("n_applications", 50000) / 50000)


def estimate_stages(stages: list[str], include_agents: bool = False) -> CostEstimate:
    s = get_settings()
    wh = s.project.warehouse
    est = CostEstimate()
    if s.project.backend == "local":
        est.lines.append("backend=local: no Databricks compute")
    else:
        minutes = sum(STAGE_WAREHOUSE_MINUTES.get(st, 1.0) for st in stages) * _scale()
        if minutes:
            minutes += wh.auto_stop_mins  # idle tail before auto-stop
        est.dbu = wh.dbu_per_hour * minutes / 60.0
        est.databricks_usd = est.dbu * wh.usd_per_dbu
        est.lines.append(
            f"warehouse {wh.cluster_size}: ~{minutes:.1f} min incl. {wh.auto_stop_mins} min auto-stop tail"
        )
    if include_agents:
        priors = s.models.get("estimate_usd_per_run", {})
        est.anthropic_usd = float(sum(priors.values()))
        est.lines.append(f"agents: {', '.join(f'{k}~${v:.2f}' for k, v in priors.items())}")
    return est


def check_cycle_caps(est: CostEstimate) -> None:
    b = get_settings().budgets
    if est.dbu > b["cycle"]["max_databricks_dbu"]:
        raise BudgetExceededError(f"Estimated {est.dbu:.2f} DBU exceeds cycle cap {b['cycle']['max_databricks_dbu']}")
    if est.anthropic_usd > b["cycle"]["max_anthropic_usd"]:
        raise BudgetExceededError(
            f"Estimated ${est.anthropic_usd:.2f} Anthropic exceeds cycle cap ${b['cycle']['max_anthropic_usd']}"
        )


def month_to_date_usd() -> float:
    from lau.store import get_store

    st = get_store("harness")
    if not st.table_exists("ops", "cost_log"):
        return 0.0
    month = datetime.now(UTC).strftime("%Y-%m")
    df = st.query(
        f"SELECT coalesce(sum(usd), 0) AS usd FROM {st.fq('ops', 'cost_log')} "
        f"WHERE substr(cast(ts AS string), 1, 7) = '{month}'"
    )
    return float(df["usd"].iloc[0] or 0.0)


def check_monthly_cap(extra_usd: float) -> None:
    cap = get_settings().budgets["monthly"]["hard_stop_usd"]
    mtd = month_to_date_usd()
    if mtd + extra_usd > cap:
        raise BudgetExceededError(f"Monthly hard stop: ${mtd:.2f} spent + ${extra_usd:.2f} planned > ${cap:.2f}")


def log_cost(kind: str, usd: float, cycle_id: str = "", dbu: float = 0.0, details: str = "") -> None:
    from lau.store import get_store

    get_store("harness").write_df(
        "ops",
        "cost_log",
        pd.DataFrame(
            [
                {
                    "ts": datetime.now(UTC),
                    "cycle_id": cycle_id,
                    "kind": kind,
                    "usd": float(usd),
                    "dbu": float(dbu),
                    "details": details,
                }
            ]
        ),
        mode="append",
    )


def metered_warehouse_usd(consume: bool = True) -> tuple[float, float]:
    """DBU/$ implied by warehouse busy time metered since the last call (plus one auto-stop tail).

    `consume=True` resets the counter so successive log entries in one process never double-count. This is an
    estimate between busy time (lower bound) and uptime; billed actuals come from system.billing.usage (`lau cost`).
    """
    global _WAREHOUSE_SECONDS
    s = get_settings()
    if s.project.backend == "local":
        return 0.0, 0.0
    wh = s.project.warehouse
    with _LOCK:
        seconds = _WAREHOUSE_SECONDS
        if consume:
            _WAREHOUSE_SECONDS = 0.0
    minutes = seconds / 60.0
    if minutes:
        minutes += wh.auto_stop_mins
    dbu = wh.dbu_per_hour * minutes / 60.0
    return dbu, dbu * wh.usd_per_dbu


def billing_actuals(days: int = 7) -> pd.DataFrame:
    """Actual DBUs for this project's warehouse from system.billing.usage (lags a few hours). Admin only."""
    from lau.store import get_store

    s = get_settings()
    wid = s.state.warehouse_id
    if s.project.backend == "local" or not wid:
        return pd.DataFrame()
    return get_store("admin").query(
        "SELECT usage_date, sku_name, sum(usage_quantity) AS dbu FROM system.billing.usage "
        f"WHERE usage_metadata.warehouse_id = '{wid}' AND usage_date >= date_sub(current_date(), {int(days)}) "
        "GROUP BY usage_date, sku_name ORDER BY usage_date"
    )
