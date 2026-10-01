"""Feature registry: engineered-feature hypotheses (sandboxed SQL expressions) with lineage and versioned
performance metadata. Performance rows are keyed by definition_version and are recomputed on definition change."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.data.features import FeatureSpec, apply_features, validate_feature_expression
from lau.harness import leakage, metrics

NAME_RE = r"^[a-z][a-z0-9_]{2,40}$"


class FeatureRegistryError(ValueError):
    pass


def register_feature(
    store,
    name: str,
    expression: str,
    rationale: str,
    hypothesis: str,
    author: str,
    cycle_id: str,
    available_columns: list[str],
    version: str,
) -> dict:
    import re

    if not re.match(NAME_RE, name):
        raise FeatureRegistryError(f"feature name must match {NAME_RE}")
    if name in available_columns:
        raise FeatureRegistryError("feature name collides with a base column")
    sources = validate_feature_expression(expression, available_columns)
    if store.table_exists("feature_registry", "features"):
        dup = store.query(f"SELECT count(*) AS n FROM {store.fq('feature_registry', 'features')} WHERE name = '{name}'")
        if int(dup["n"].iloc[0]):
            raise FeatureRegistryError(f"feature '{name}' already registered")
    row = {
        "feature_id": f"ft-{uuid.uuid4().hex[:10]}",
        "name": name,
        "expression": expression,
        "source_columns": json.dumps(sources),
        "rationale": rationale[:2000],
        "hypothesis": hypothesis[:2000],
        "author": author,
        "cycle_id": cycle_id,
        "created_at": datetime.now(UTC),
        "created_under_definition": version,
        "status": "proposed",
    }
    store.write_df("feature_registry", "features", pd.DataFrame([row]), mode="append")
    return row


def evaluate_features(
    store, specs: list[FeatureSpec], train: pd.DataFrame, catalog: pd.DataFrame, leak_cfg: dict, version: str
) -> pd.DataFrame:
    """Univariate screening on TRAIN only (no validation use => not a counted test)."""
    if not specs:
        return pd.DataFrame()
    frame = apply_features(train, specs)
    y = frame["label"].to_numpy()
    risk = dict(zip(catalog["variable"], catalog["leakage_risk"], strict=False))
    proxy = dict(zip(catalog["variable"], catalog["proxy_risk"], strict=False))
    months = sorted(frame["origination_month"].unique())
    early = frame["origination_month"].isin(months[: len(months) // 2])
    rows = []
    for sp in specs:
        x = frame[sp.name]
        f = leakage.check_column(frame, sp.name, y, leak_cfg)
        inherited_leak = [c for c in sp.source_columns if risk.get(c) == "high"]
        inherited_proxy = [c for c in sp.source_columns if proxy.get(c) == "high"]
        rows.append(
            {
                "name": sp.name,
                "definition_version": version,
                "evaluated_at": datetime.now(UTC),
                "univariate_auc_train": f.single_feature_auc if f.single_feature_auc is not None else np.nan,
                "missing_rate": float(x.isna().mean()),
                "psi_first_vs_second_half_train": metrics.psi(x[early], x[~early]),
                "leakage_risk": "high" if inherited_leak or f.risk == "high" else f.risk,
                "proxy_risk": "high" if inherited_proxy else "low",
                "notes": "; ".join(
                    f.reasons
                    + [f"inherits leak from {inherited_leak}"] * bool(inherited_leak)
                    + [f"built from proxy {inherited_proxy}"] * bool(inherited_proxy)
                ),
            }
        )
    out = pd.DataFrame(rows)
    return out


def write_performance(store, perf: pd.DataFrame, version: str) -> None:
    if perf.empty:
        return
    store.write_df(
        "feature_registry",
        "feature_performance",
        perf,
        mode="replace_partition",
        partition={"definition_version": version},
    )


# Lifecycle: proposed (by an agent) -> screened (passes the leakage and proxy screen under the active definition) or
# rejected_screen (fails it). A person's rejection ("rejected") is final. "Used" is derived from evaluations.
SCREENABLE = ("proposed", "screened", "rejected_screen")


def screen_statuses(store, perf: pd.DataFrame) -> dict[str, int]:
    """Set each screened feature's status from this definition's screen, in one statement."""
    if perf.empty:
        return {"screened": 0, "rejected_screen": 0}
    bad = perf[(perf["leakage_risk"] == "high") | (perf["proxy_risk"] == "high")]["name"].tolist()
    good = [n for n in perf["name"].tolist() if n not in bad]

    def names(xs: list[str]) -> str:
        return ", ".join("'" + str(x).replace("'", "''") + "'" for x in xs) or "''"

    allowed = ", ".join(f"'{x}'" for x in SCREENABLE)
    store.execute(
        f"UPDATE {store.fq('feature_registry', 'features')} SET status = CASE "
        f"WHEN name IN ({names(bad)}) THEN 'rejected_screen' WHEN name IN ({names(good)}) THEN 'screened' "
        f"ELSE status END WHERE status IN ({allowed})"
    )
    return {"screened": len(good), "rejected_screen": len(bad)}


def set_status(store, name: str, status: str) -> None:
    store.execute(f"UPDATE {store.fq('feature_registry', 'features')} SET status = '{status}' WHERE name = '{name}'")
