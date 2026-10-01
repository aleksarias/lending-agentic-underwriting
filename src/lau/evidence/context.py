"""Shared inputs for one evidence run: one run_id and timestamp, every lake table read at most once, all lazily.

Steps take an `EvidenceContext` so a full run builds the benchmark labels once and feeds the benchmark ledger, the
definition-sensitivity table, the vintage curves and the verdict from the same frames. Running a single step only
loads what that step touches.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from functools import cached_property

import pandas as pd

from lau.data.splits import read_split_meta
from lau.definition.label_builder import build_labels
from lau.definition.registry import active_version
from lau.evidence import ledger, metrics_flat, registry_sync
from lau.evidence.config import Benchmark, BenchmarkConfig, load_benchmark_config, resolve_benchmarks
from lau.settings import Settings, get_settings
from lau.store import Store, get_store

LOAN_COLUMNS = ["loan_id", "application_id", "origination_month", "decision_ts"]
EVALUATION_COLUMNS = [
    "eval_id",
    "candidate_ref",
    "definition_version",
    "ts",
    "passed_validation",
    "val_auc",
    "reference_auc",
    "required_margin",
    "n_tests",
    "result_json",
]


class EvidenceNotReadyError(RuntimeError):
    """A prerequisite for a step (active definition, raw data load, ...) does not exist yet."""


def eligible(labels: pd.DataFrame) -> pd.DataFrame:
    """Labelled loans that count: not excluded and not censored."""
    return labels[~labels["is_excluded"] & ~labels["is_censored"]]


class EvidenceContext:
    def __init__(
        self,
        store: Store | None = None,
        log: Callable[[str], None] = print,
        cfg: BenchmarkConfig | None = None,
        computed_at: datetime | None = None,
    ) -> None:
        self.store = store or get_store("harness")
        self.log = log
        self.cfg = cfg or load_benchmark_config()
        self.computed_at = computed_at or datetime.now(UTC)
        self.run_id = f"evr-{self.computed_at:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}"
        self.settings: Settings = get_settings()
        self.benchmark_rows: pd.DataFrame | None = None  # set by the benchmark step of this run
        self._labels: dict[str, pd.DataFrame] = {}

    # ---- configuration ------------------------------------------------------------------------------------
    @cached_property
    def benchmarks(self) -> list[Benchmark]:
        return resolve_benchmarks(self.cfg)

    @property
    def primary(self) -> Benchmark:
        return next(b for b in self.benchmarks if b.key == self.cfg.primary)

    @property
    def longest_window_months(self) -> int:
        return max(b.definition.observation_window_months for b in self.benchmarks)

    # ---- versions and raw data ------------------------------------------------------------------------------
    @cached_property
    def active_version(self) -> str:
        v = active_version(self.store)
        if v is None:
            raise EvidenceNotReadyError("no active definition: run `lau default-definition apply` first")
        return v

    @cached_property
    def data_version(self) -> dict:
        row = ledger.latest_data_version(self.store)
        if row is None:
            raise EvidenceNotReadyError("no data load recorded in ops.data_version: run `lau gen-data` first")
        return row

    @property
    def as_of_month(self) -> str:
        return str(self.data_version["as_of_month"])

    @cached_property
    def data_versions(self) -> pd.DataFrame:
        if not self.store.table_exists("ops", "data_version"):
            return pd.DataFrame(columns=["data_version", "created_at"])
        return self.store.query(
            f"SELECT data_version, created_at FROM {self.store.fq('ops', 'data_version')} ORDER BY created_at"
        )

    def data_version_at(self, ts: datetime | None) -> str | None:
        """The data version that was current when something was created (None if it predates every load)."""
        if ts is None or self.data_versions.empty:
            return None
        t = pd.Timestamp(ts)
        t = t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t
        before = self.data_versions[pd.to_datetime(self.data_versions["created_at"]) <= t]
        return None if before.empty else str(before["data_version"].iloc[-1])

    @cached_property
    def all_apps(self) -> pd.DataFrame:
        """Every application, approved or not (through the door)."""
        return self.store.query(f"SELECT * FROM {self.store.fq('curated', 'applications')}")

    @cached_property
    def apps(self) -> pd.DataFrame:
        """Approved applications = funded loans, with every curated column (what models score)."""
        return self.all_apps[self.all_apps["approved"].fillna(False).astype(bool)].reset_index(drop=True)

    @cached_property
    def loans(self) -> pd.DataFrame:
        return self.apps[LOAN_COLUMNS]

    @cached_property
    def perf(self) -> pd.DataFrame:
        return self.store.query(f"SELECT * FROM {self.store.fq('raw', 'performance')}")

    def labels(self, bench: Benchmark) -> pd.DataFrame:
        """Labels of the whole loan book under a benchmark definition (built once per run)."""
        if bench.key not in self._labels:
            self._labels[bench.key] = build_labels(self.perf, self.loans, bench.definition, self.as_of_month)
        return self._labels[bench.key]

    # ---- splits -------------------------------------------------------------------------------------------
    @cached_property
    def validation_range(self) -> tuple[str, str]:
        meta = read_split_meta(self.store, self.active_version)
        return str(meta["val_start"]), str(meta["val_end"])

    @cached_property
    def validation_months(self) -> tuple[str, ...]:
        """Origination months of the active definition's validation window that have funded loans."""
        lo, hi = self.validation_range
        return tuple(sorted(m for m in self.apps["origination_month"].unique() if lo <= m <= hi))

    @cached_property
    def oot_ranges(self) -> list[tuple[str, str]]:
        """Out-of-time month ranges of EVERY definition version (metadata only, never the holdout labels)."""
        df = self.store.query(f"SELECT oot_start, oot_end FROM {self.store.fq('labels', 'split_meta')}")
        return [(str(a), str(b)) for a, b in zip(df["oot_start"], df["oot_end"], strict=True)]

    # ---- registry and evaluations ---------------------------------------------------------------------------
    @cached_property
    def registry(self) -> list[registry_sync.RegistryVersion]:
        return registry_sync.list_versions()

    @cached_property
    def evaluations(self) -> pd.DataFrame:
        if not self.store.table_exists("ops", "evaluations"):
            return pd.DataFrame(columns=EVALUATION_COLUMNS)
        return self.store.query(f"SELECT * FROM {self.store.fq('ops', 'evaluations')} ORDER BY ts")

    @cached_property
    def eval_metrics(self) -> pd.DataFrame:
        return metrics_flat.flatten_evaluations(self.evaluations, self.log)

    @cached_property
    def evaluated_versions(self) -> set[str]:
        """Candidate versions the harness has evaluated (baseline or candidate) under the active definition."""
        e = self.evaluations
        refs = e.loc[e["definition_version"] == self.active_version, "candidate_ref"].astype(str)
        parts = [r.split(":", 1) for r in refs if ":" in r]
        return {v for kind, v in parts if kind in ("candidate", "baseline")}

    def current_benchmark_rows(self) -> pd.DataFrame:
        """This run's benchmark rows if the benchmark step ran, else the latest stored run (may be empty)."""
        if self.benchmark_rows is not None:
            return self.benchmark_rows
        return ledger.latest_benchmark_rows(self.store)
