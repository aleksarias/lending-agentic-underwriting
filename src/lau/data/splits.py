"""Time-based splits only (by origination month). Recomputed per definition_version, because eligibility and
maturity (hence which months hold labelled loans) change with the definition."""

from __future__ import annotations

import json

import pandas as pd


class SplitError(RuntimeError):
    pass


def compute_splits(labels: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    version = labels["definition_version"].iloc[0]
    elig = labels[~labels["is_excluded"] & ~labels["is_censored"]].copy()
    if elig.empty:
        raise SplitError("no eligible labelled loans for this definition")
    counts = elig.groupby("origination_month").size().sort_index()
    cum = counts.cumsum() / counts.sum()
    months = list(counts.index)
    train_m = [m for m in months if cum[m] <= cfg["train_frac"]]
    val_m = [m for m in months if cfg["train_frac"] < cum[m] <= cfg["train_frac"] + cfg["validation_frac"]]
    oot_m = [m for m in months if m not in train_m and m not in val_m]
    if not train_m or not val_m or not oot_m:
        raise SplitError(f"too few labelled months for a 3-way time split: {len(months)} months")

    split_of = {**{m: "train" for m in train_m}, **{m: "validation" for m in val_m}, **{m: "oot" for m in oot_m}}
    elig["split"] = elig["origination_month"].map(split_of)
    n_es = max(1, int(round(len(train_m) * cfg.get("early_stopping_tail_frac", 0.15))))
    es_months = set(train_m[-n_es:])
    elig["es_tail"] = elig["origination_month"].isin(es_months) & (elig["split"] == "train")

    meta = {
        "definition_version": version,
        "train_start": train_m[0],
        "train_end": train_m[-1],
        "val_start": val_m[0],
        "val_end": val_m[-1],
        "oot_start": oot_m[0],
        "oot_end": oot_m[-1],
        "es_tail_start": sorted(es_months)[0],
        "n": {k: int(v) for k, v in elig["split"].value_counts().items()},
        "default_rate": {k: float(v) for k, v in elig.groupby("split")["label"].mean().items()},
    }
    splits = elig[["definition_version", "loan_id", "application_id", "origination_month", "split", "es_tail"]]
    return splits.reset_index(drop=True), meta


def meta_frame(meta: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **{k: v for k, v in meta.items() if not isinstance(v, dict)},
                "n_json": json.dumps(meta["n"]),
                "default_rate_json": json.dumps(meta["default_rate"]),
            }
        ]
    )


def read_split_meta(store, version: str) -> dict:
    df = store.query(f"SELECT * FROM {store.fq('labels', 'split_meta')} WHERE definition_version = '{version}'")
    if df.empty:
        raise SplitError(f"no split metadata for {version}")
    row = df.iloc[0].to_dict()
    row["n"] = json.loads(row.pop("n_json"))
    row["default_rate"] = json.loads(row.pop("default_rate_json"))
    return row
