"""Shadow scoring: challengers score new applications next to the serving model WITHOUT affecting decisions.

Writes ops.shadow_scores (never production, never a decision table), keyed by definition_version, so results under
different definitions are never mixed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.definition.registry import active_version
from lau.modeling import registry_io
from lau.store import get_store


def run_shadow(log=print) -> dict:
    st = get_store("harness")
    version = active_version(st)
    apps = st.query(f"SELECT * FROM {st.fq('curated', 'new_applications')}")
    scored: dict[str, np.ndarray] = {}
    serving = registry_io.serving_model("harness")
    rows = []
    if serving:
        m = registry_io.load_pd_model(
            f"models:/{registry_io.production_model_name()}/{serving['model_version']}", "harness"
        )
        scored["serving"] = m.predict_pd(apps)
        rows.append(("serving", serving["model_version"], serving.get("definition_version"), scored["serving"]))
    ch = registry_io.alias_version(registry_io.candidate_model_name(), registry_io.challenger_alias(version), "harness")
    if ch:
        m = registry_io.load_pd_model(registry_io.candidate_uri(ch[0]), "harness")
        scored["challenger"] = m.predict_pd(apps)
        rows.append(("challenger", ch[0], ch[1].get("definition_version"), scored["challenger"]))
    if not rows:
        ref = st.query(
            f"SELECT baseline_model_version FROM {st.fq('ops', 'harness_reference')} "
            f"WHERE definition_version = '{version}'"
        )
        mv = str(ref["baseline_model_version"].iloc[0])
        rows.append(
            (
                "baseline",
                mv,
                version,
                registry_io.load_pd_model(registry_io.candidate_uri(mv), "harness").predict_pd(apps),
            )
        )
    ts = datetime.now(UTC)
    out = pd.concat(
        [
            pd.DataFrame(
                {
                    "scored_at": ts,
                    "definition_version": version,
                    "role": role,
                    "model_version": mv,
                    "model_definition_version": mdv,
                    "application_id": apps["application_id"],
                    "origination_month": apps["origination_month"],
                    "pd": p,
                }
            )
            for role, mv, mdv, p in rows
        ],
        ignore_index=True,
    )
    st.write_df("ops", "shadow_scores", out, mode="append")
    summary = {r[0]: {"model_version": r[1], "model_definition": r[2], "mean_pd": float(np.mean(r[3]))} for r in rows}
    if "serving" in scored and "challenger" in scored:
        rate = 0.7
        a = scored["serving"] <= np.quantile(scored["serving"], rate)
        b = scored["challenger"] <= np.quantile(scored["challenger"], rate)
        summary["decision_agreement_at_70pct"] = float((a == b).mean())
    log(f"shadow-scored {len(apps):,} new applications: {summary}")
    return summary
