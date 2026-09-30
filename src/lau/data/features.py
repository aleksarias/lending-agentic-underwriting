"""Feature matrix assembly: curated application columns + registered engineered features (sandboxed SQL)."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from lau.definition.labels_io import read_labels
from lau.definition.sql_predicate import evaluate_expression, validate_expression
from lau.settings import get_settings

# Never model inputs: identifiers, timestamps, bookkeeping.
META_COLUMNS = {
    "application_id",
    "loan_id",
    "application_ts",
    "decision_ts",
    "origination_month",
    "approved",
    "definition_version",
    "label",
    "split",
    "es_tail",
}


def prohibited_features() -> set[str]:
    return set(get_settings().protected.get("prohibited_features", []))


def is_timestamp_col(name: str) -> bool:
    return name.endswith("_ts")


def base_feature_columns(columns: list[str]) -> list[str]:
    bad = META_COLUMNS | prohibited_features()
    return [c for c in columns if c not in bad and not is_timestamp_col(c)]


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    expression: str
    source_columns: tuple[str, ...]

    @staticmethod
    def from_row(row: dict) -> FeatureSpec:
        return FeatureSpec(row["name"], row["expression"], tuple(json.loads(row["source_columns"])))


def validate_feature_expression(expression: str, available: list[str]) -> list[str]:
    """Validate an engineered-feature expression; return referenced source columns."""
    allowed = {c.lower() for c in base_feature_columns(available)}
    tree = validate_expression(expression, allowed)
    from sqlglot import exp

    return sorted({c.name.lower() for c in tree.find_all(exp.Column)})


def apply_features(df: pd.DataFrame, specs: list[FeatureSpec]) -> pd.DataFrame:
    out = df.copy()
    allowed = {c.lower() for c in base_feature_columns(list(df.columns))}
    for spec in specs:
        out[spec.name] = pd.to_numeric(evaluate_expression(df, spec.expression, allowed), errors="coerce")
    return out


def load_dev_frame(store, version: str, consumer: str, splits=("train", "validation")) -> pd.DataFrame:
    """Dev-period applications joined to active-version labels. Works for agent (views) and harness roles."""
    labels = read_labels(store, version, consumer, splits=tuple(splits))
    table = "applications_dev" if store.role == "agent" else "applications"
    apps = store.query(f"SELECT * FROM {store.fq('curated', table)} WHERE approved")
    df = apps.merge(
        labels[["application_id", "label", "split", "es_tail", "definition_version"]], on="application_id", how="inner"
    )
    df["es_tail"] = df["es_tail"].fillna(False).astype(bool)
    return df


def registered_specs(store, names: list[str] | None = None) -> list[FeatureSpec]:
    if not store.table_exists("feature_registry", "features"):
        return []
    df = store.query(f"SELECT * FROM {store.fq('feature_registry', 'features')} WHERE status <> 'rejected'")
    if names is not None:
        df = df[df["name"].isin(names)]
    return [FeatureSpec.from_row(r) for r in df.to_dict("records")]
