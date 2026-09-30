"""Paired-bootstrap statistics for the benchmark ledger: pure numpy/pandas, no I/O.

Every model in a benchmark is scored on the same loans and judged on the same bootstrap resamples, so a difference
between two models is a paired difference and its interval is meaningful (a model's AUC moves with the sample; the
difference between two models on that sample moves much less).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from lau.harness.metrics import auc

CHUNK_ELEMENTS = 4_000_000  # resamples x loans processed per block, bounds memory on large windows


def resample_indices(n: int, resamples: int, seed: int) -> np.ndarray:
    """(resamples, n) bootstrap row indices; the same matrix is reused for every model of a benchmark."""
    return np.random.default_rng(seed).integers(0, n, size=(resamples, n))


def _blocks(idx: np.ndarray):
    step = max(1, CHUNK_ELEMENTS // max(idx.shape[1], 1))
    for i in range(0, idx.shape[0], step):
        yield idx[i : i + step]


def auc_by_resample(y: np.ndarray, s: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """AUC of risk score `s` on every resample (Mann-Whitney via average ranks); NaN where a resample has one class."""
    out = []
    for block in _blocks(idx):
        ys = y[block]
        ranks = pd.DataFrame(s[block]).rank(axis=1, method="average").to_numpy()
        n_pos = ys.sum(axis=1)
        n_neg = ys.shape[1] - n_pos
        with np.errstate(invalid="ignore", divide="ignore"):
            a = ((ranks * ys).sum(axis=1) - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
        out.append(np.where((n_pos > 0) & (n_neg > 0), a, np.nan))
    return np.concatenate(out)


def bad_rate(y: np.ndarray, s: np.ndarray, approval_rate: float) -> float:
    """Default rate among the `approval_rate` share with the lowest risk score (ties at the cutoff are approved)."""
    approved = s <= np.quantile(s, approval_rate)
    return float(y[approved].mean())


def bad_rate_by_resample(y: np.ndarray, s: np.ndarray, idx: np.ndarray, approval_rate: float) -> np.ndarray:
    out = []
    for block in _blocks(idx):
        sb, yb = s[block], y[block]
        approved = sb <= np.quantile(sb, approval_rate, axis=1)[:, None]
        out.append((yb * approved).sum(axis=1) / approved.sum(axis=1))
    return np.concatenate(out)


def interval(samples: np.ndarray, level: float) -> tuple[float, float]:
    """Percentile interval of the finite bootstrap samples."""
    finite = np.asarray(samples, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size < 2:
        return float("nan"), float("nan")
    lo, hi = np.percentile(finite, [100 * (1 - level) / 2, 100 * (1 + level) / 2])
    return float(lo), float(hi)


@dataclass(frozen=True)
class Estimate:
    value: float
    lo: float
    hi: float


@dataclass(frozen=True)
class ModelStats:
    auc: Estimate
    bad_rate: Estimate
    vs_reference: Estimate | None  # None for the reference itself
    vs_best_known: Estimate | None  # None when there is no other non-reference model to compare with
    best_known_versus: str | None  # key of the model `vs_best_known` is measured against


@dataclass(frozen=True)
class BenchmarkStats:
    models: dict[str, ModelStats]
    best_known: str | None  # highest AUC excluding the reference
    best_auc: str  # highest AUC among all models (may be the reference)
    best_bad_rate: str  # lowest bad rate among all models


def _estimate(point: float, samples: np.ndarray, level: float) -> Estimate:
    lo, hi = interval(samples, level)
    return Estimate(point, lo, hi)


def _first_best(values: dict[str, float], keys: list[str], highest: bool) -> str | None:
    """Best key by value; ties go to the earliest key in `keys` (a deterministic, documented order)."""
    best: str | None = None
    for k in keys:
        v = values[k]
        if v != v:
            continue
        if best is None or (v > values[best] if highest else v < values[best]):
            best = k
    return best


def benchmark_stats(
    y: np.ndarray,
    scores: dict[str, np.ndarray],
    reference_key: str,
    approval_rate: float,
    resamples: int,
    seed: int,
    level: float,
) -> BenchmarkStats:
    """AUC, bad rate at a fixed approval rate, and paired differences vs the reference and vs the best known model.

    `scores` maps model key -> risk score (higher = riskier), aligned to `y`; its order breaks ties. The reference
    (`reference_key`) must be one of the keys. Best known = highest AUC excluding the reference; the best known model
    itself is compared with the second best so its difference is the margin by which it leads.
    """
    y = np.asarray(y).astype(int)
    idx = resample_indices(len(y), resamples, seed)
    full = {k: auc(y, s) for k, s in scores.items()}
    boot = {k: auc_by_resample(y, s, idx) for k, s in scores.items()}
    bad_full = {k: bad_rate(y, s, approval_rate) for k, s in scores.items()}
    models = [k for k in scores if k != reference_key]
    best_known = _first_best(full, models, highest=True)
    ranked = sorted(models, key=lambda k: -full[k] if full[k] == full[k] else float("inf"))

    out: dict[str, ModelStats] = {}
    for k, s in scores.items():
        bad = _estimate(bad_full[k], bad_rate_by_resample(y, s, idx, approval_rate), level)
        vs_ref = None
        if k != reference_key:
            vs_ref = _estimate(full[k] - full[reference_key], boot[k] - boot[reference_key], level)
        versus = None
        if best_known is not None:
            versus = best_known if k != best_known else next((m for m in ranked if m != k), None)
        vs_best = None
        if versus is not None:
            vs_best = _estimate(full[k] - full[versus], boot[k] - boot[versus], level)
        out[k] = ModelStats(
            auc=_estimate(full[k], boot[k], level),
            bad_rate=bad,
            vs_reference=vs_ref,
            vs_best_known=vs_best,
            best_known_versus=versus,
        )
    keys = list(scores)
    return BenchmarkStats(
        models=out,
        best_known=best_known,
        best_auc=_first_best(full, keys, highest=True) or keys[0],
        best_bad_rate=_first_best(bad_full, keys, highest=False) or keys[0],
    )
