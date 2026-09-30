"""`lau gen-data`: generate synthetic data and write raw tables + ground truth (admin identity)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pandas as pd

from lau.settings import STATE_DIR, get_settings
from lau.store import get_store
from lau.synth.generator import generate


def data_version(cfg: dict, n: int) -> str:
    return hashlib.sha256(json.dumps({**cfg, "n_applications": n}, sort_keys=True).encode()).hexdigest()[:12]


def gen_data(n_applications: int | None = None, seed: int | None = None, log=print) -> dict:
    s = get_settings()
    cfg = dict(s.synth)
    if seed is not None:
        cfg["seed"] = seed
    n = int(n_applications or cfg["n_applications"])
    d = generate(cfg, n_applications=n)
    st = get_store("admin")
    st.write_df("raw", "applications_raw", d.applications, mode="overwrite")
    log(f"raw.applications_raw: {len(d.applications):,} rows x {d.applications.shape[1]} cols")
    st.write_df("raw", "performance", d.performance, mode="overwrite")
    log(f"raw.performance: {len(d.performance):,} loan-months")
    st.write_df("raw", "protected_attributes", d.protected, mode="overwrite")
    st.write_df("raw", "field_lineage", d.field_lineage, mode="overwrite")
    st.write_df("raw", "new_applications_raw", d.new_applications, mode="overwrite")
    dv = data_version(cfg, n)
    st.write_df(
        "ops",
        "data_version",
        pd.DataFrame(
            [
                {
                    "data_version": dv,
                    "created_at": datetime.now(UTC),
                    "as_of_month": cfg["as_of_month"],
                    "seed": cfg["seed"],
                    "n_applications": n,
                    "ground_truth_json": json.dumps(d.ground_truth),
                }
            ]
        ),
        mode="append",
    )
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "ground_truth.json").write_text(json.dumps(d.ground_truth, indent=2))
    log(f"data_version {dv}; ground truth -> .lau/ground_truth.json (never shown to agents)")
    return {"data_version": dv, **{k: d.ground_truth[k] for k in ("approval_rate", "fraud_share")}}
