"""Deterministic scoring metrics. Pure functions of (y, p) or (expected, actual) arrays."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


def auc(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y)
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, p))


def ks(y: np.ndarray, p: np.ndarray) -> float:
    y, p = np.asarray(y), np.asarray(p)
    if len(np.unique(y)) < 2:
        return float("nan")
    order = np.argsort(p)
    y = y[order]
    cum_bad = np.cumsum(y) / y.sum()
    cum_good = np.cumsum(1 - y) / (1 - y).sum()
    return float(np.max(np.abs(cum_bad - cum_good)))


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    df = pd.DataFrame({"y": np.asarray(y), "p": np.asarray(p)})
    df["bin"] = pd.qcut(df["p"].rank(method="first"), bins, labels=False)
    t = df.groupby("bin").agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean")).reset_index()
    return t


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    t = calibration_table(y, p, bins)
    return float((t["n"] * (t["predicted"] - t["observed"]).abs()).sum() / t["n"].sum())


def calibration_slope_intercept(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    p = np.clip(np.asarray(p), 1e-6, 1 - 1e-6)
    logit = np.log(p / (1 - p)).reshape(-1, 1)
    if len(np.unique(y)) < 2:
        return float("nan"), float("nan")
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(logit, y)
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def lift_by_decile(y: np.ndarray, p: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame({"y": np.asarray(y), "p": np.asarray(p)})
    df["decile"] = 10 - pd.qcut(df["p"].rank(method="first"), 10, labels=False)  # 1 = riskiest
    base = df["y"].mean()
    t = df.groupby("decile").agg(n=("y", "size"), default_rate=("y", "mean"), mean_pd=("p", "mean")).reset_index()
    t["lift"] = t["default_rate"] / base if base else np.nan
    t["cum_capture"] = (t["default_rate"] * t["n"]).cumsum() / (df["y"].sum() or 1)
    return t


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """Population stability index using expected-sample quantile bins (numeric)."""
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    expected = expected[~np.isnan(expected)]
    actual = actual[~np.isnan(actual)]
    if len(expected) == 0 or len(actual) == 0:
        return float("nan")
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    e = np.histogram(expected, edges)[0] / len(expected)
    a = np.histogram(actual, edges)[0] / len(actual)
    e, a = np.clip(e, 1e-4, None), np.clip(a, 1e-4, None)
    return float(np.sum((a - e) * np.log(a / e)))


def psi_categorical(expected: pd.Series, actual: pd.Series) -> float:
    e = expected.astype(str).value_counts(normalize=True)
    a = actual.astype(str).value_counts(normalize=True)
    idx = e.index.union(a.index)
    e, a = e.reindex(idx).fillna(0).clip(lower=1e-4), a.reindex(idx).fillna(0).clip(lower=1e-4)
    return float(((a - e) * np.log(a / e)).sum())


def psi_bins(expected: np.ndarray, bins: int = 10) -> list[float]:
    """Quantile edges of a baseline distribution (for monitoring baselines)."""
    edges = np.unique(np.quantile(np.asarray(expected, dtype=float), np.linspace(0, 1, bins + 1)))
    return [float(x) for x in edges]


def psi_from_edges(edges: list[float], expected_share: list[float], actual: np.ndarray) -> float:
    e_arr = np.array(edges, dtype=float)
    e_arr[0], e_arr[-1] = -np.inf, np.inf
    a = np.histogram(np.asarray(actual, dtype=float), e_arr)[0] / max(len(actual), 1)
    e = np.clip(np.array(expected_share), 1e-4, None)
    a = np.clip(a, 1e-4, None)
    return float(np.sum((a - e) * np.log(a / e)))


def _oof_target_encoding(x: pd.Series, y: np.ndarray, folds: int = 5, smoothing: float = 20.0) -> np.ndarray:
    """Out-of-fold, smoothed category means. In-sample encoding lets a high-cardinality field memorize the target,
    which would make e.g. zip3 look like a leak (AUC ~0.9) when it carries little signal."""
    keys = x.astype(str).to_numpy()
    prior = float(np.mean(y))
    fold = np.arange(len(y)) % folds
    np.random.default_rng(0).shuffle(fold)
    out = np.empty(len(y), dtype=float)
    for k in range(folds):
        tr, te = fold != k, fold == k
        stats = pd.DataFrame({"k": keys[tr], "y": y[tr]}).groupby("k")["y"].agg(["sum", "count"])
        enc = (stats["sum"] + smoothing * prior) / (stats["count"] + smoothing)
        out[te] = pd.Series(keys[te]).map(enc).fillna(prior).to_numpy()
    return out


def univariate_auc(x: pd.Series, y: np.ndarray) -> float:
    """Direction-free single-feature AUC (max(auc, 1-auc)). Categorical -> out-of-fold smoothed category rate."""
    y = np.asarray(y)
    if (
        x.dtype == object
        or isinstance(x.dtype, pd.CategoricalDtype)
        or pd.api.types.is_string_dtype(x)
        or pd.api.types.is_bool_dtype(x)
    ):
        score = _oof_target_encoding(x, y)
    else:
        xv = pd.to_numeric(x, errors="coerce").astype(float)
        score = xv.fillna(xv.median() if xv.notna().any() else 0.0).to_numpy()
    a = auc(y, score)
    return float(max(a, 1 - a)) if not np.isnan(a) else float("nan")


def summary(y: np.ndarray, p: np.ndarray) -> dict:
    y, p = np.asarray(y), np.clip(np.asarray(p), 1e-6, 1 - 1e-6)
    slope, intercept = calibration_slope_intercept(y, p)
    return {
        "n": int(len(y)),
        "default_rate": float(np.mean(y)) if len(y) else float("nan"),
        "auc": auc(y, p),
        "ks": ks(y, p),
        "brier": float(brier_score_loss(y, p)) if len(y) else float("nan"),
        "log_loss": float(log_loss(y, p, labels=[0, 1])) if len(y) else float("nan"),
        "ece": ece(y, p) if len(y) >= 10 else float("nan"),
        "calibration_slope": slope,
        "calibration_intercept": intercept,
        "mean_pd": float(np.mean(p)) if len(p) else float("nan"),
    }
