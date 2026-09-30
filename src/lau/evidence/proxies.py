"""Proxy scan -> `ops.proxy_scan`: how well each feature alone predicts protected-group membership.

For every base variable of the active definition's data catalog (prohibited ones skipped) and every protected class
in config/protected_classes.yaml, one row for "pooled" (any protected group vs everyone else) and one row per
protected group (that group vs the reference group, when it has at least 50 members). `proxy_auc` is the
direction-free single-feature AUC (`univariate_auc`); `flagged` = above `thresholds.fairness.proxy_auc_flag`.

Protected attributes are read here by the harness only; the table holds aggregates, never row-level attributes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lau.evidence import schemas
from lau.evidence.context import EvidenceContext
from lau.harness.metrics import univariate_auc

SAMPLE_SIZE = 20_000
MIN_GROUP = 50
POOLED = "pooled"


def scan(features: pd.DataFrame, protected: pd.DataFrame, classes: dict, threshold: float) -> pd.DataFrame:
    """Proxy AUC of every feature column of `features` (keyed by application_id) against every protected class."""
    df = features.merge(protected, on="application_id", how="inner")
    cols = [c for c in features.columns if c != "application_id"]
    rows = []
    for cname, spec in classes.items():
        col = spec["column"]
        if col not in df:
            continue
        g = df[col].astype(str)
        groups = [str(x) for x in spec["protected_groups"]]
        ref = str(spec["reference_group"])
        comparisons = [(POOLED, np.ones(len(df), bool), g.isin(groups).to_numpy())]
        for grp in groups:
            if (g == grp).sum() >= MIN_GROUP:
                comparisons.append((grp, g.isin([grp, ref]).to_numpy(), (g == grp).to_numpy()))
        for f in cols:
            for grp, keep, member in comparisons:
                a = univariate_auc(df.loc[keep, f], member[keep].astype(int))
                if a == a:
                    rows.append(
                        {
                            "feature": f,
                            "protected_class": cname,
                            "protected_group": grp,
                            "proxy_auc": a,
                            "flagged": bool(a > threshold),
                        }
                    )
    return pd.DataFrame(rows, columns=["feature", "protected_class", "protected_group", "proxy_auc", "flagged"])


def catalog_variables(ctx: EvidenceContext) -> list[str]:
    """Base variables of the active definition's catalog, prohibited ones excluded."""
    st = ctx.store
    if not st.table_exists("curated", "data_catalog"):
        return []
    cat = st.query(
        f"SELECT * FROM {st.fq('curated', 'data_catalog')} WHERE definition_version = '{ctx.active_version}'"
    )
    if "variable_kind" in cat:
        cat = cat[cat["variable_kind"] == "base"]
    if "prohibited" in cat:
        cat = cat[~cat["prohibited"].fillna(False).astype(bool)]
    return [v for v in cat["variable"] if v in ctx.all_apps.columns]


def compute(ctx: EvidenceContext) -> pd.DataFrame:
    variables = catalog_variables(ctx)
    if not variables:
        ctx.log("proxies: no catalog variables for the active definition; nothing written")
        return schemas.conform("proxy_scan", pd.DataFrame())
    apps = ctx.all_apps
    sample = apps[["application_id", *variables]].sample(min(len(apps), SAMPLE_SIZE), random_state=0)
    protected = ctx.store.read_table("raw", "protected_attributes")
    out = scan(
        sample,
        protected,
        ctx.settings.protected["protected_classes"],
        float(ctx.settings.thresholds["fairness"]["proxy_auc_flag"]),
    )
    out.insert(0, "definition_version", ctx.active_version)
    out.insert(0, "run_id", ctx.run_id)
    out.insert(0, "computed_at", ctx.computed_at)
    ctx.log(
        f"proxies: {len(variables)} variable(s) x protected groups = {len(out)} row(s), "
        f"{int(out['flagged'].sum())} flagged above {ctx.settings.thresholds['fairness']['proxy_auc_flag']}"
    )
    return schemas.conform("proxy_scan", out)
