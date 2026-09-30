"""Benchmark ledger -> `ops.benchmark_results`.

Every registered model (all versions of the candidate and production models) and the frozen reference score are
re-scored on the SAME loans under each frozen benchmark definition (config/benchmarks.yaml), so "is the system
improving?" is answered on fixed yardsticks no matter which definition of default is active or which models were
trained under which definition.

Window policy (config `window.policy`):
  validation                        the active definition's validation months (models may have been selected on
                                    them, which `selected_on_window` flags as optimistic)
  latest_matured_excluding_holdout  the most recent run of fully matured origination months that lie inside NO
                                    definition's out-of-time range; falls back to `validation` when none qualify

Labels come from `build_labels`; the holdout schema is never read.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from lau.evidence import registry_sync, schemas
from lau.evidence.config import REFERENCE_LABEL, Benchmark
from lau.evidence.context import EvidenceContext, EvidenceNotReadyError, eligible
from lau.evidence.stats import BenchmarkStats, Estimate, benchmark_stats
from lau.modeling import registry_io

METRICS = ("auc", "bad_rate_at_fixed_approval", "auc_minus_reference", "auc_minus_best_known")


@dataclass(frozen=True)
class Window:
    policy: str  # the policy actually applied (`validation` after a fallback)
    months: tuple[str, ...]

    @property
    def start(self) -> str:
        return self.months[0]

    @property
    def end(self) -> str:
        return self.months[-1]


@dataclass(frozen=True)
class ModelInfo:
    key: str
    name: str
    version: str | None
    label: str
    kind: str
    trained_definition: str | None
    trained_data_version: str | None
    selected_on_window: bool


@dataclass(frozen=True)
class ScoredModel:
    info: ModelInfo
    risk: np.ndarray  # aligned to the window frame


# ---- window ---------------------------------------------------------------------------------------------------
def latest_matured_months(
    loan_months, as_of: str, min_months: int, oot_ranges: list[tuple[str, str]], n_months: int
) -> list[str]:
    """Latest run (up to `n_months`) of consecutive origination months that have at least `min_months` of
    performance by `as_of` and fall inside none of the out-of-time ranges. Empty if no month qualifies."""
    as_of_p = pd.Period(as_of, "M")
    free = sorted(
        m
        for m in set(loan_months)
        if (as_of_p - pd.Period(m, "M")).n >= min_months and not any(a <= m <= b for a, b in oot_ranges)
    )
    run: list[str] = []
    for m in reversed(free):
        if run and pd.Period(m, "M") + 1 != pd.Period(run[-1], "M"):
            break
        run.append(m)
        if len(run) == n_months:
            break
    return sorted(run)


def resolve_window(ctx: EvidenceContext) -> Window:
    validation = ctx.validation_months
    if ctx.cfg.window.policy == "latest_matured_excluding_holdout":
        months = latest_matured_months(
            ctx.loans["origination_month"],
            ctx.as_of_month,
            ctx.longest_window_months,
            ctx.oot_ranges,
            ctx.cfg.window.months,
        )
        if months:
            return Window("latest_matured_excluding_holdout", tuple(months))
        ctx.log("benchmark: no matured, non-holdout origination months qualify; falling back to the validation window")
    if not validation:
        raise EvidenceNotReadyError("the validation window contains no funded loans")
    return Window("validation", validation)


# ---- scoring --------------------------------------------------------------------------------------------------
def _selected_on_window(ctx: EvidenceContext, v: registry_sync.RegistryVersion, window: Window) -> bool:
    """The harness evaluated this model on the validation months that the benchmark window overlaps (optimistic)."""
    if not set(window.months) & set(ctx.validation_months):
        return False
    evaluated = v.version if v.registry == "candidate" else v.source_candidate_version
    return evaluated in ctx.evaluated_versions


def score_models(ctx: EvidenceContext, frame: pd.DataFrame, window: Window) -> list[ScoredModel]:
    """Risk scores of every registry version on `frame`; versions that cannot load or score are logged and skipped."""
    out: list[ScoredModel] = []
    for v in ctx.registry:
        try:
            model = registry_io.load_pd_model(v.uri, "harness")
        except Exception as e:  # noqa: BLE001 - one broken version must not sink the ledger
            ctx.log(f"  skipped {v.key}: cannot load ({type(e).__name__}: {str(e)[:160]})")
            continue
        try:
            risk = np.asarray(model.predict_pd(frame), dtype=float)
            if risk.shape != (len(frame),) or not np.isfinite(risk).all():
                raise ValueError("predictions are missing or not finite")
        except Exception as e:  # noqa: BLE001
            ctx.log(f"  skipped {v.key}: cannot score ({type(e).__name__}: {str(e)[:160]})")
            continue
        info = ModelInfo(
            key=v.key,
            name=v.model_name,
            version=v.version,
            label=registry_sync.label_of(v),
            kind=registry_sync.kind_of(v),
            trained_definition=v.definition_version,
            trained_data_version=v.tags.get("data_version") or ctx.data_version_at(v.created_at),
            selected_on_window=_selected_on_window(ctx, v, window),
        )
        out.append(ScoredModel(info, risk))
    return out


def reference_risk(ctx: EvidenceContext, frame: pd.DataFrame) -> np.ndarray:
    """Risk score of the frozen reference (legacy score: higher = safer, so risk = -score)."""
    ref = ctx.cfg.reference
    if ref.column not in frame:
        raise EvidenceNotReadyError(f"reference column {ref.column!r} is not in curated.applications")
    x = pd.to_numeric(frame[ref.column], errors="coerce")
    if x.notna().sum() == 0:
        raise EvidenceNotReadyError(f"reference column {ref.column!r} has no values in the benchmark window")
    x = x.fillna(x.median())  # keep the loan set identical across models
    return (-x if ref.direction == "higher_is_safer" else x).to_numpy(dtype=float)


# ---- rows -----------------------------------------------------------------------------------------------------
def _row(common: dict, model: dict, metric: str, est: Estimate, best: bool = False, versus: str | None = None) -> dict:
    return {
        **common,
        **model,
        "metric": metric,
        "value": est.value,
        "ci_lo": est.lo,
        "ci_hi": est.hi,
        "is_best": best,
        "versus_key": versus,
    }


def _rows(
    ctx: EvidenceContext,
    window: Window,
    bench: Benchmark,
    infos: dict[str, ModelInfo],
    stats: BenchmarkStats,
    n: int,
    n_defaults: int,
) -> list[dict]:
    common = {
        "computed_at": ctx.computed_at,
        "run_id": ctx.run_id,
        "window_policy": window.policy,
        "window_start": window.start,
        "window_end": window.end,
        "performance_as_of": ctx.as_of_month,
        "data_version": ctx.data_version["data_version"],
        "benchmark_key": bench.key,
        "benchmark_dpd": bench.dpd,
        "benchmark_version": bench.version,
        "n": n,
        "n_defaults": n_defaults,
    }
    out: list[dict] = []
    for key, st in stats.models.items():
        i = infos[key]
        model = {
            "model_key": i.key,
            "model_name": i.name,
            "model_version": i.version,
            "model_label": i.label,
            "model_kind": i.kind,
            "trained_definition": i.trained_definition,
            "trained_data_version": i.trained_data_version,
            "selected_on_window": i.selected_on_window,
        }
        out.append(_row(common, model, "auc", st.auc, best=key == stats.best_auc))
        out.append(_row(common, model, "bad_rate_at_fixed_approval", st.bad_rate, best=key == stats.best_bad_rate))
        if st.vs_reference is not None:
            out.append(_row(common, model, "auc_minus_reference", st.vs_reference, versus=ctx.cfg.reference.key))
        if st.vs_best_known is not None:
            out.append(_row(common, model, "auc_minus_best_known", st.vs_best_known, versus=st.best_known_versus))
    return out


def compute(ctx: EvidenceContext) -> pd.DataFrame:
    window = resolve_window(ctx)
    frame = ctx.apps[ctx.apps["origination_month"].isin(window.months)].reset_index(drop=True)
    ctx.log(f"benchmark: {window.policy} window {window.start}..{window.end}, {len(frame):,} funded loans")

    scored = score_models(ctx, frame, window)
    ref_key = ctx.cfg.reference.key
    infos = {m.info.key: m.info for m in scored}
    infos[ref_key] = ModelInfo(ref_key, ref_key, None, REFERENCE_LABEL, "reference", None, None, False)
    scores = {m.info.key: m.risk for m in scored}
    scores[ref_key] = reference_risk(ctx, frame)  # last: the reference never wins a tie
    ctx.log(f"  scored {len(scored)} model version(s) plus the frozen reference")

    position = pd.Series(np.arange(len(frame)), index=frame["application_id"])
    b = ctx.cfg.bootstrap
    rows: list[dict] = []
    for bench in ctx.benchmarks:
        lab = eligible(ctx.labels(bench))
        lab = lab[lab["origination_month"].isin(window.months)]
        take = position.reindex(lab["application_id"]).to_numpy()
        ok = ~np.isnan(take)
        y = lab["label"].astype(int).to_numpy()[ok]
        take = take[ok].astype(int)
        if len(y) == 0 or y.min() == y.max():
            ctx.log(f"  {bench.key}: skipped (no loans, or only one outcome, in the window)")
            continue
        stats = benchmark_stats(
            y,
            {k: s[take] for k, s in scores.items()},
            ref_key,
            ctx.cfg.fixed_approval_rate,
            b.resamples,
            b.seed,
            b.level,
        )
        rows += _rows(ctx, window, bench, infos, stats, n=int(len(y)), n_defaults=int(y.sum()))
        best = infos[stats.best_known].label if stats.best_known else "none"
        ctx.log(
            f"  {bench.key}: n={len(y):,} defaults={int(y.sum()):,}; best known {best}; "
            f"reference AUC {stats.models[ref_key].auc.value:.4f}"
        )
    return schemas.conform("benchmark_results", pd.DataFrame(rows))
