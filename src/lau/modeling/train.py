"""Training from the fixed template. Trains on the TRAIN split only (early stopping on its last months)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from lau.data.features import FeatureSpec, base_feature_columns, load_dev_frame, registered_specs
from lau.harness import metrics
from lau.modeling.model import PDModel
from lau.modeling.search_space import MAX_FEATURES, SearchSpaceError, validate_params


def default_feature_set(store, version: str) -> list[str]:
    """Baseline features: catalog variables not flagged high leakage risk or proxy risk."""
    cat = store.query(
        f"SELECT variable, leakage_risk, proxy_risk FROM {store.fq('curated', 'data_catalog')} "
        f"WHERE definition_version = '{version}' AND variable_kind = 'base'"
    )
    ok = cat[(cat["leakage_risk"] != "high") & (cat["proxy_risk"] != "high")]["variable"].tolist()
    return sorted(ok)


def train_model(
    store,
    version: str,
    model_type: str,
    params: dict | None,
    features: list[str],
    engineered: list[str] | None = None,
    consumer: str = "modeling",
) -> tuple[PDModel, pd.DataFrame, dict]:
    params = validate_params(model_type, params)
    engineered = engineered or []
    if len(features) + len(engineered) > MAX_FEATURES * 3:
        raise SearchSpaceError("too many features")
    df = load_dev_frame(store, version, consumer, splits=("train",))
    specs: list[FeatureSpec] = registered_specs(store, engineered) if engineered else []
    missing_eng = set(engineered) - {s.name for s in specs}
    if missing_eng:
        raise SearchSpaceError(f"engineered features not registered: {sorted(missing_eng)}")
    allowed = set(base_feature_columns(list(df.columns)))
    bad = [f for f in features if f not in allowed]
    if bad:
        raise SearchSpaceError(f"features not allowed or unknown: {bad[:10]}")
    model = PDModel(model_type, params, list(features) + [s.name for s in specs], specs, version)
    y = df["label"].to_numpy()
    model.fit(df, y, es_mask=df["es_tail"].to_numpy())
    fit_rows = ~df["es_tail"].to_numpy()
    p = model.predict_pd(df)
    train_metrics = {
        f"train_{k}": v for k, v in metrics.summary(y[fit_rows], p[fit_rows]).items() if isinstance(v, float | int)
    }
    if (~fit_rows).any():
        train_metrics.update(
            {f"es_{k}": v for k, v in metrics.summary(y[~fit_rows], p[~fit_rows]).items() if isinstance(v, float | int)}
        )
    return model, df, train_metrics


def score_frame(model: PDModel, df: pd.DataFrame) -> np.ndarray:
    return model.predict_pd(df)
