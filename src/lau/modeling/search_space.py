"""Bounded hyper-parameter search space. The modeling agent may only choose values inside these ranges."""

from __future__ import annotations

from typing import Any

SEARCH_SPACE: dict[str, dict[str, dict[str, Any]]] = {
    "logreg": {
        "C": {"type": "float", "min": 1e-3, "max": 10.0, "default": 0.1},
        "penalty": {"type": "choice", "values": ["l2", "l1"], "default": "l2"},
    },
    "lightgbm": {
        "n_estimators": {"type": "int", "min": 50, "max": 1500, "default": 600},
        "learning_rate": {"type": "float", "min": 0.005, "max": 0.2, "default": 0.03},
        "num_leaves": {"type": "int", "min": 4, "max": 64, "default": 15},
        "min_data_in_leaf": {"type": "int", "min": 20, "max": 1000, "default": 100},
        "feature_fraction": {"type": "float", "min": 0.3, "max": 1.0, "default": 0.8},
        "bagging_fraction": {"type": "float", "min": 0.5, "max": 1.0, "default": 0.8},
        "bagging_freq": {"type": "int", "min": 0, "max": 10, "default": 1},
        "lambda_l2": {"type": "float", "min": 0.0, "max": 50.0, "default": 5.0},
        "max_cat_to_onehot": {"type": "int", "min": 2, "max": 16, "default": 8},
    },
    "xgboost": {
        "n_estimators": {"type": "int", "min": 50, "max": 1500, "default": 600},
        "eta": {"type": "float", "min": 0.005, "max": 0.2, "default": 0.03},
        "max_depth": {"type": "int", "min": 2, "max": 8, "default": 4},
        "min_child_weight": {"type": "float", "min": 1.0, "max": 200.0, "default": 20.0},
        "subsample": {"type": "float", "min": 0.5, "max": 1.0, "default": 0.8},
        "colsample_bytree": {"type": "float", "min": 0.3, "max": 1.0, "default": 0.8},
        "lambda": {"type": "float", "min": 0.0, "max": 50.0, "default": 5.0},
    },
}

MAX_FEATURES = 60


class SearchSpaceError(ValueError):
    pass


def validate_params(model_type: str, params: dict[str, Any] | None) -> dict[str, Any]:
    if model_type not in SEARCH_SPACE:
        raise SearchSpaceError(f"model_type must be one of {sorted(SEARCH_SPACE)}")
    space = SEARCH_SPACE[model_type]
    params = dict(params or {})
    unknown = set(params) - set(space)
    if unknown:
        raise SearchSpaceError(f"unknown params for {model_type}: {sorted(unknown)}")
    out: dict[str, Any] = {}
    for name, spec in space.items():
        v = params.get(name, spec["default"])
        if spec["type"] == "choice":
            if v not in spec["values"]:
                raise SearchSpaceError(f"{name} must be one of {spec['values']}")
        else:
            v = int(v) if spec["type"] == "int" else float(v)
            if not spec["min"] <= v <= spec["max"]:
                raise SearchSpaceError(f"{name}={v} outside [{spec['min']}, {spec['max']}]")
        out[name] = v
    return out


def defaults(model_type: str) -> dict[str, Any]:
    return validate_params(model_type, {})
