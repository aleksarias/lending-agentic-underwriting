"""Concrete pipeline stages and the invalidation DAG.

    ingest ─▶ curate ─▶ labels ─▶ splits ─▶ catalog ─▶ feature_registry_eval ─▶ baseline_retrain
                           │                                                      │
                           └─▶ lessons                                             ▼
                                   │                                     harness_reference ─▶ monitoring_baseline
                                   └───────────────────────────────────────────────┴──────────────▶ improvement_cycle

Every definition-dependent stage writes rows tagged with `definition_version` (partition-replaced, never deleting
other versions), so old versions remain queryable and multiple definitions can coexist side by side.
Stages run as the harness/pipeline identity.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.data import feature_registry as freg
from lau.data.catalog_stats import build_catalog
from lau.data.features import load_dev_frame, registered_specs
from lau.data.splits import compute_splits, meta_frame, read_split_meta
from lau.definition.label_builder import build_labels, label_summary
from lau.definition.labels_io import read_all_labels_for_version
from lau.definition.schema import DefaultDefinition
from lau.pipeline.dag import Pipeline, Stage
from lau.settings import get_settings
from lau.store import Store, get_store


@dataclass
class PipelineContext:
    version: str
    definition: DefaultDefinition
    activate: bool = True  # False for side-by-side compare builds (no active views, no cycle)
    run_cycle: bool = False
    previous_version: str | None = None
    log: Callable[[str], None] = print
    store: Store = field(default_factory=lambda: get_store("harness"))
    extras: dict = field(default_factory=dict)

    @property
    def allow_inactive(self) -> bool:
        return not self.activate


# ---------------------------------------------------------------------------------------------------------
def data_fingerprint(ctx: PipelineContext) -> str:
    st = ctx.store
    if not st.table_exists("ops", "data_version"):
        return "no-data"
    df = st.query(f"SELECT data_version FROM {st.fq('ops', 'data_version')} ORDER BY created_at DESC LIMIT 1")
    return str(df["data_version"].iloc[0]) if len(df) else "no-data"


def stage_ingest(ctx: PipelineContext) -> dict:
    if data_fingerprint(ctx) == "no-data":
        raise RuntimeError("no raw data: run `lau gen-data` first")
    return {"data_version": data_fingerprint(ctx)}


def stage_curate(ctx: PipelineContext) -> dict:
    from lau.synth import cashflow
    from lau.synth.generator import PII_COLUMNS, PROTECTED_COLUMNS

    st = ctx.store
    raw = st.query(f"SELECT * FROM {st.fq('raw', 'applications_raw')}")
    cur = raw.drop(columns=[c for c in PII_COLUMNS + PROTECTED_COLUMNS if c in raw.columns])
    cf_info: dict = {}
    if st.table_exists("raw", "bank_transactions"):
        # Monthly cash flows from PRE-decision transactions only (guard lives in cashflow.monthly_sql), then
        # per-applicant cf_* features. Post-decision rows exist in raw but never reach curated/model inputs.
        months = int(get_settings().synth["cashflow"]["months_history"])
        st.execute(
            f"CREATE OR REPLACE TABLE {st.fq('curated', 'cashflow_monthly')} AS "
            + cashflow.monthly_sql(st.fq("raw", "bank_transactions"), months)
        )
        monthly = st.query(f"SELECT * FROM {st.fq('curated', 'cashflow_monthly')}")
        feats = cashflow.summarize_monthly(monthly, cur.set_index("application_id")["annual_income"])
        cur = cur.drop(columns=[c for c in cashflow.CASHFLOW_FEATURES if c in cur.columns]).merge(
            feats, on="application_id", how="left"
        )
        cf_info = {"cashflow_monthly_rows": len(monthly), "cashflow_features": len(cashflow.CASHFLOW_FEATURES)}
    st.write_df("curated", "applications", cur, mode="overwrite")
    lin = st.query(f"SELECT * FROM {st.fq('raw', 'field_lineage')}")
    st.write_df("curated", "field_lineage", lin, mode="overwrite")
    newapps = st.query(f"SELECT * FROM {st.fq('raw', 'new_applications_raw')}")
    if cf_info:
        newapps = newapps.merge(
            cashflow.summarize_monthly(
                st.query(f"SELECT * FROM {st.fq('curated', 'cashflow_monthly')} WHERE application_id LIKE 'N%'"),
                newapps.set_index("application_id")["annual_income"],
            ),
            on="application_id",
            how="left",
        )
    st.write_df(
        "curated",
        "new_applications",
        newapps.drop(columns=[c for c in PROTECTED_COLUMNS if c in newapps.columns]),
        mode="overwrite",
    )
    return {"n_applications": len(cur), "n_columns": cur.shape[1], **cf_info}


def stage_labels(ctx: PipelineContext) -> dict:
    st = ctx.store
    perf = st.query(f"SELECT * FROM {st.fq('raw', 'performance')}")
    loans = st.query(
        f"SELECT loan_id, application_id, origination_month, decision_ts "
        f"FROM {st.fq('curated', 'applications')} WHERE approved"
    )
    as_of = st.query(f"SELECT as_of_month FROM {st.fq('ops', 'data_version')} ORDER BY created_at DESC LIMIT 1")
    labels = build_labels(perf, loans, ctx.definition, str(as_of["as_of_month"].iloc[0]))
    st.write_df("labels", "labels_all", labels, mode="replace_partition", partition={"definition_version": ctx.version})
    summary = label_summary(labels)
    prev = _label_stats(st, ctx.previous_version) if ctx.previous_version else None
    change = {}
    if prev:
        change = {
            "prev_version": ctx.previous_version,
            "default_rate_change_pp": round(100 * (summary["default_rate"] - prev["default_rate"]), 3),
            "n_default_change": summary["n_default"] - prev["n_default"],
            "n_eligible_change": summary["n_eligible"] - prev["n_eligible"],
        }
        ctx.log(f"  label change vs {ctx.previous_version}: {change}")
    st.write_df(
        "ops",
        "label_stats",
        pd.DataFrame(
            [
                {
                    "definition_version": ctx.version,
                    "created_at": datetime.now(UTC),
                    "summary_json": json.dumps(summary),
                    "change_json": json.dumps(change),
                }
            ]
        ),
        mode="replace_partition",
        partition={"definition_version": ctx.version},
    )
    return {**{k: v for k, v in summary.items() if not isinstance(v, dict)}, **change}


def _label_stats(st: Store, version: str | None) -> dict | None:
    if not version or not st.table_exists("ops", "label_stats"):
        return None
    df = st.query(f"SELECT summary_json FROM {st.fq('ops', 'label_stats')} WHERE definition_version = '{version}'")
    return None if df.empty else json.loads(df["summary_json"].iloc[0])


def stage_splits(ctx: PipelineContext) -> dict:
    s, st = get_settings(), ctx.store
    labels = read_all_labels_for_version(st, ctx.version, "stage.splits", allow_inactive=ctx.allow_inactive)
    splits, meta = compute_splits(labels, s.thresholds["splits"])
    part = {"definition_version": ctx.version}
    st.write_df("labels", "splits", splits, mode="replace_partition", partition=part)
    st.write_df("labels", "split_meta", meta_frame(meta), mode="replace_partition", partition=part)
    oot = labels.merge(splits[splits["split"] == "oot"][["loan_id"]], on="loan_id")
    st.write_df(
        "holdout",
        "oot_labels",
        oot[["definition_version", "loan_id", "application_id", "origination_month", "label"]],
        mode="replace_partition",
        partition=part,
    )
    if ctx.activate:
        refresh_active_views(st, ctx.version, meta["oot_start"])
    return {k: v for k, v in meta.items()}


def refresh_active_views(st: Store, version: str, oot_start: str) -> None:
    st.create_view(
        "labels",
        "labels_active",
        "SELECT l.definition_version, l.loan_id, l.application_id, l.origination_month, l.decision_ts, "
        "l.label, s.split, s.es_tail "
        f"FROM {st.fq('labels', 'labels_all')} l JOIN {st.fq('labels', 'splits')} s "
        "ON l.loan_id = s.loan_id AND l.definition_version = s.definition_version "
        f"WHERE l.definition_version = '{version}' AND s.split = 'train' "
        "AND NOT l.is_excluded AND NOT l.is_censored",
    )
    st.create_view(
        "curated",
        "applications_dev",
        f"SELECT * FROM {st.fq('curated', 'applications')} WHERE origination_month < '{oot_start}'",
    )
    if st.table_exists("curated", "cashflow_monthly"):
        st.create_view(
            "curated",
            "cashflow_monthly_dev",
            f"SELECT m.* FROM {st.fq('curated', 'cashflow_monthly')} m JOIN {st.fq('curated', 'applications')} a "
            f"ON m.application_id = a.application_id WHERE a.origination_month < '{oot_start}'",
        )
    from lau.governance.uc_layout import apply_object_grants

    apply_object_grants(st)


def stage_catalog(ctx: PipelineContext) -> dict:
    s, st = get_settings(), ctx.store
    dev = _dev_frame(ctx)
    apps = st.query(f"SELECT * FROM {st.fq('curated', 'applications')}")
    meta = read_split_meta(st, ctx.version)
    apps_dev = apps[apps["origination_month"] < meta["oot_start"]]
    cat = build_catalog(
        apps_dev,
        dev[dev["split"] == "train"],
        dev[dev["split"] == "validation"],
        st.query(f"SELECT * FROM {st.fq('curated', 'field_lineage')}"),
        st.query(f"SELECT * FROM {st.fq('raw', 'protected_attributes')}"),
        s.thresholds["leakage"],
        s.thresholds["fairness"],
        s.protected["protected_classes"],
        ctx.version,
    )
    st.write_df("curated", "data_catalog", cat, mode="replace_partition", partition={"definition_version": ctx.version})
    if ctx.activate:
        from lau.governance.uc_layout import apply_object_grants

        apply_object_grants(st)
    return {
        "n_variables": len(cat),
        "high_leakage": cat[cat["leakage_risk"] == "high"]["variable"].tolist(),
        "high_proxy": cat[cat["proxy_risk"] == "high"]["variable"].tolist(),
    }


def _dev_frame(ctx: PipelineContext) -> pd.DataFrame:
    if ctx.activate:
        return load_dev_frame(ctx.store, ctx.version, "stage")
    # compare mode: explicit opt-in to an inactive version
    from lau.definition import labels_io

    labels = labels_io.read_labels(ctx.store, ctx.version, "stage.compare", allow_inactive=True)
    apps = ctx.store.query(f"SELECT * FROM {ctx.store.fq('curated', 'applications')} WHERE approved")
    df = apps.merge(labels[["application_id", "label", "split", "es_tail", "definition_version"]], on="application_id")
    df["es_tail"] = df["es_tail"].fillna(False).astype(bool)
    return df


def stage_feature_registry_eval(ctx: PipelineContext) -> dict:
    s, st = get_settings(), ctx.store
    specs = registered_specs(st)
    if not specs:
        return {"n_features": 0}
    dev = _dev_frame(ctx)
    cat = st.query(f"SELECT * FROM {st.fq('curated', 'data_catalog')} WHERE definition_version = '{ctx.version}'")
    perf = freg.evaluate_features(st, specs, dev[dev["split"] == "train"], cat, s.thresholds["leakage"], ctx.version)
    freg.write_performance(st, perf, ctx.version)
    return {"n_features": len(perf), "high_leakage": perf[perf["leakage_risk"] == "high"]["name"].tolist()}


def stage_baseline_retrain(ctx: PipelineContext) -> dict:
    """Retrain the regularized-LR baseline and the current champion ARCHITECTURE from scratch under this version.

    Nothing is promoted: the retrained champion architecture is only a candidate for the new definition.
    """
    from lau.modeling import registry_io
    from lau.modeling.model import PDModel
    from lau.modeling.search_space import defaults
    from lau.modeling.train import default_feature_set

    st = ctx.store
    dev = _dev_frame(ctx)
    train = dev[dev["split"] == "train"].reset_index(drop=True)
    feats = default_feature_set(st, ctx.version)
    out = {}
    base = PDModel("logreg", defaults("logreg"), feats, [], ctx.version).fit(
        train, train["label"].to_numpy(), es_mask=train["es_tail"].to_numpy()
    )
    _, mv = registry_io.log_candidate(
        base,
        {},
        {"lau_role": "baseline", "author": "pipeline"},
        train,
        role="harness",
        run_name=f"baseline_{ctx.version[:8]}",
    )
    out["baseline_model_version"] = mv

    arch = _latest_champion_architecture(exclude_version=ctx.version)
    if arch:
        specs = registered_specs(st, arch["engineered"]) if arch["engineered"] else []
        base_feats = [f for f in arch["features"] if f not in {sp.name for sp in specs} and f in train.columns]
        m = PDModel(arch["model_type"], arch["params"], base_feats + [sp.name for sp in specs], specs, ctx.version)
        m.fit(train, train["label"].to_numpy(), es_mask=train["es_tail"].to_numpy())
        _, mv2 = registry_io.log_candidate(
            m,
            {},
            {
                "lau_role": "retrained_champion_arch",
                "author": "pipeline",
                "source_champion_version": arch["model_version"],
                "source_definition_version": arch["definition_version"],
            },
            train,
            role="harness",
            run_name=f"champ_arch_{ctx.version[:8]}",
        )
        out["retrained_champion_arch_model_version"] = mv2
    st.write_df(
        "ops",
        "baselines",
        pd.DataFrame(
            [{"definition_version": ctx.version, "created_at": datetime.now(UTC), "details_json": json.dumps(out)}]
        ),
        mode="replace_partition",
        partition={"definition_version": ctx.version},
    )
    return out


def _latest_champion_architecture(exclude_version: str) -> dict | None:
    from lau.modeling import registry_io

    serving = registry_io.serving_model("harness")
    if not serving or serving.get("definition_version") == exclude_version:
        return None
    model = registry_io.load_pd_model(
        f"models:/{registry_io.production_model_name()}/{serving['model_version']}", "harness"
    )
    d = model.describe()
    return {**d, "model_version": serving["model_version"]}


def stage_harness_reference(ctx: PipelineContext) -> dict:
    from lau.harness.evaluate import evaluate_model
    from lau.harness.multiple_testing import record, required_margin
    from lau.modeling import registry_io

    s, st = get_settings(), ctx.store
    bl = st.query(f"SELECT details_json FROM {st.fq('ops', 'baselines')} WHERE definition_version = '{ctx.version}'")
    details = json.loads(bl["details_json"].iloc[0])
    mv = details["baseline_model_version"]
    model = registry_io.load_pd_model(registry_io.candidate_uri(mv), "harness")
    if not ctx.activate:
        return {"baseline_model_version": mv, "note": "compare mode: reference computed in compare report"}
    ev = evaluate_model(model, ctx.version, f"baseline:{mv}", count_test=False, compare_to_reference=False)
    record(st, ctx.version, "reset", purpose="reset")
    st.write_df(
        "ops",
        "harness_reference",
        pd.DataFrame(
            [
                {
                    "definition_version": ctx.version,
                    "created_at": datetime.now(UTC),
                    "baseline_model_version": mv,
                    "val_auc": ev["validation"]["auc"],
                    "val_ks": ev["validation"]["ks"],
                    "val_ece": ev["validation"]["ece"],
                    "val_default_rate": ev["validation"]["default_rate"],
                    "required_margin_at_1": required_margin(1, s.thresholds["gate"]),
                    "thresholds_json": json.dumps(s.thresholds),
                    "eval_id": ev["eval_id"],
                }
            ]
        ),
        mode="replace_partition",
        partition={"definition_version": ctx.version},
    )
    return {"baseline_model_version": mv, "val_auc": ev["validation"]["auc"], "passed": ev["passed_validation"]}


def stage_monitoring_baseline(ctx: PipelineContext) -> dict:
    """PSI baselines, expected default rate by score band, alert thresholds; re-baselines shadow scoring too."""
    from lau.harness import metrics
    from lau.modeling import registry_io

    s, st = get_settings(), ctx.store
    if not ctx.activate:
        return {"skipped": "compare mode"}
    champ = registry_io.champion_for(ctx.version)
    if champ:
        ref_kind, mv, model = "champion", champ[0], champ[1]
        uri = f"models:/{registry_io.production_model_name()}/{mv}"
    else:
        ref = st.query(
            f"SELECT baseline_model_version FROM {st.fq('ops', 'harness_reference')} "
            f"WHERE definition_version = '{ctx.version}'"
        )
        ref_kind, mv = "baseline", str(ref["baseline_model_version"].iloc[0])
        uri = registry_io.candidate_uri(mv)
        model = registry_io.load_pd_model(uri, "harness")
    dev = load_dev_frame(st, ctx.version, "stage.monitoring_baseline")
    val = dev[dev["split"] == "validation"]
    p = model.predict_pd(val)
    edges = metrics.psi_bins(p, 10)
    shares = list(np.histogram(p, np.r_[-np.inf, edges[1:-1], np.inf])[0] / len(p))
    val = val.assign(pd_=p, band=pd.qcut(pd.Series(p).rank(method="first"), 10, labels=False).to_numpy())
    exp_by_band = val.groupby("band").agg(expected_pd=("pd_", "mean"), observed=("label", "mean")).reset_index()
    top = list(model.feature_importance())[:10]
    feat_base = {}
    for f in top:
        if f in val and pd.api.types.is_numeric_dtype(val[f]):
            x = pd.to_numeric(val[f], errors="coerce").dropna()
            if len(x) > 50:
                e = metrics.psi_bins(x, 10)
                sh = list(np.histogram(x, np.r_[-np.inf, e[1:-1], np.inf])[0] / len(x))
                feat_base[f] = {"edges": e, "shares": sh}
    st.write_df(
        "ops",
        "monitoring_baseline",
        pd.DataFrame(
            [
                {
                    "definition_version": ctx.version,
                    "created_at": datetime.now(UTC),
                    "reference_kind": ref_kind,
                    "reference_model_uri": uri,
                    "score_edges_json": json.dumps(edges),
                    "score_shares_json": json.dumps(shares),
                    "expected_by_band_json": exp_by_band.to_json(orient="records"),
                    "expected_default_rate": float(val["label"].mean()),
                    "feature_baselines_json": json.dumps(feat_base),
                    "thresholds_json": json.dumps(s.thresholds["monitoring"]),
                }
            ]
        ),
        mode="replace_partition",
        partition={"definition_version": ctx.version},
    )
    return {"reference": ref_kind, "model_uri": uri, "expected_default_rate": float(val["label"].mean())}


def stage_lessons(ctx: PipelineContext) -> dict:
    from lau.agents.lessons import revalidate_for_definition

    if not ctx.activate:
        return {"skipped": "compare mode"}
    return revalidate_for_definition(ctx.version)


def stage_improvement_cycle(ctx: PipelineContext) -> dict:
    st = ctx.store
    if not ctx.activate:
        return {"skipped": "compare mode"}
    st.write_df(
        "ops",
        "cycle_queue",
        pd.DataFrame(
            [
                {
                    "requested_at": datetime.now(UTC),
                    "definition_version": ctx.version,
                    "reason": "definition_change",
                    "status": "queued",
                }
            ]
        ),
        mode="append",
    )
    if ctx.run_cycle:
        from lau.agents.orchestrator import run_cycle_sync

        report = run_cycle_sync(reason="definition_change")
        return {"cycle": report.get("cycle_id"), "status": report.get("status")}
    return {"queued": True}


def config_fingerprint(ctx: PipelineContext) -> str:
    s = get_settings()
    return hashlib.sha256(json.dumps([s.thresholds, s.protected], sort_keys=True).encode()).hexdigest()[:12]


def build_pipeline() -> Pipeline:
    return Pipeline(
        [
            Stage("ingest", stage_ingest, (), False, "1", "raw synthetic data present", root_input=data_fingerprint),
            Stage("curate", stage_curate, ("ingest",), False, "1", "raw -> curated (drop PII/protected)"),
            Stage("labels", stage_labels, ("curate",), True, "1", "derive labels from raw performance"),
            Stage(
                "lessons",
                stage_lessons,
                ("labels",),
                True,
                "1",
                "re-tag LESSONS.md for the new definition",
                mode_sensitive=True,
            ),
            Stage("splits", stage_splits, ("labels",), True, "1", "time-based train/validation/OOT splits"),
            Stage(
                "catalog",
                stage_catalog,
                ("splits",),
                True,
                "1",
                "data catalog stats, leakage & proxy risk",
                root_input=config_fingerprint,
            ),
            Stage(
                "feature_registry_eval",
                stage_feature_registry_eval,
                ("catalog",),
                True,
                "1",
                "re-evaluate registered features against the new label",
            ),
            Stage(
                "baseline_retrain",
                stage_baseline_retrain,
                ("feature_registry_eval",),
                True,
                "1",
                "retrain baseline + champion architecture from scratch",
            ),
            Stage(
                "harness_reference",
                stage_harness_reference,
                ("baseline_retrain",),
                True,
                "1",
                "reference metrics, thresholds, reset experiment counter",
                root_input=config_fingerprint,
                mode_sensitive=True,
            ),
            Stage(
                "monitoring_baseline",
                stage_monitoring_baseline,
                ("harness_reference",),
                True,
                "1",
                "PSI baselines, expected default rates, alert thresholds (shadow + monitoring)",
                mode_sensitive=True,
            ),
            Stage(
                "improvement_cycle",
                stage_improvement_cycle,
                ("monitoring_baseline", "lessons"),
                True,
                "1",
                "restart the improvement loop",
                mode_sensitive=True,
            ),
        ]
    )


def read_state(st: Store) -> pd.DataFrame:
    if not st.table_exists("ops", "pipeline_state"):
        return pd.DataFrame(columns=["stage", "fingerprint", "status"])
    return st.query(
        f"SELECT stage, definition_version, fingerprint, status, finished_at FROM {st.fq('ops', 'pipeline_state')}"
    )


def write_state(st: Store, row: dict) -> None:
    st.write_df("ops", "pipeline_state", pd.DataFrame([row]), mode="append")
