"""Requirement A tests (a)-(e) plus schema/hash/sandbox behaviour."""

from __future__ import annotations

import pytest
import yaml

from lau.definition.hashing import definition_version
from lau.definition.label_builder import build_labels, label_summary
from lau.definition.schema import SEMANTIC_FIELDS, DefaultDefinition, load_definition
from lau.definition.sql_predicate import UnsafeExpressionError, normalize_predicate

# One alternative value per semantic field. If a field is added to the schema, this test forces an update.
ALTERNATIVES = {
    "delinquency_threshold_dpd": 60,
    "delinquency_timing": "end_of_window",
    "observation_window_months": 18,
    "min_seasoning_months": 6,
    "maturity_rule": "censor",
    "include_charge_off": False,
    "include_bankruptcy": False,
    "include_settlement": False,
    "include_forbearance_as_default": True,
    "cure_handling": {"mode": "cured_not_default", "cure_months_required": 3},
    "exclusions": ["fraud_confirmed"],
    "early_payoff_within_months": 6,
    "balance_materiality_threshold": 0.0,
    "custom_sql_predicate": "dpd >= 30 AND past_due_amount > 1000",
}

DEFINITION_DEPENDENT = [
    "labels",
    "lessons",
    "splits",
    "catalog",
    "feature_registry_eval",
    "baseline_retrain",
    "harness_reference",
    "monitoring_baseline",
    "improvement_cycle",
]


def _base(cfg_dir) -> DefaultDefinition:
    return load_definition(cfg_dir / "default_definition.yaml")


def test_alternatives_cover_every_semantic_field():
    assert set(ALTERNATIVES) == set(SEMANTIC_FIELDS)


# ---- (a) every field change -> new hash -> the right invalidations ---------------------------------------
@pytest.mark.parametrize("field", sorted(ALTERNATIVES))
def test_a_field_change_changes_hash_and_invalidates_downstream(lake, cfg_dir, definition_yaml, field):
    from lau.pipeline import definition_ops as ops

    base = _base(cfg_dir)
    changed = definition_yaml({field: ALTERNATIVES[field]})
    new = load_definition(changed)
    assert definition_version(new) != definition_version(base)

    plan = ops.plan(changed, with_impact=False)
    assert plan.version == definition_version(new)
    assert [k for k, _, _ in plan.diff] == [field]
    stale = set(plan.stale)
    assert stale == set(DEFINITION_DEPENDENT), f"{field}: {sorted(stale)}"
    assert "ingest" not in stale and "curate" not in stale  # raw/curated data are definition-independent


# ---- (b) unchanged definition -> nothing runs -----------------------------------------------------------
def test_b_unchanged_definition_is_idempotent(lake, cfg_dir):
    from lau.pipeline import definition_ops as ops

    plan = ops.plan(cfg_dir / "default_definition.yaml", with_impact=False)
    assert plan.is_noop and plan.stale == []
    res = ops.apply(
        cfg_dir / "default_definition.yaml",
        confirm=lambda q: pytest.fail("must not prompt"),
        run_cycle=False,
        log=lambda m: None,
    )
    assert res.get("noop") and res["ran"] == []


def test_b_formatting_and_metadata_do_not_change_hash(cfg_dir, definition_yaml):
    base = definition_version(_base(cfg_dir))
    meta_only = definition_yaml({"metadata": {"name": "renamed", "description": "x", "owner": "y"}})
    assert definition_version(load_definition(meta_only)) == base
    d = yaml.safe_load((cfg_dir / "default_definition.yaml").read_text())
    d["exclusions"] = list(reversed(d["exclusions"])) + [d["exclusions"][0]]  # order + duplicate
    assert definition_version(DefaultDefinition(**d)) == base
    p1 = DefaultDefinition(**{**d, "custom_sql_predicate": "dpd>=30 and past_due_amount>1000"})
    p2 = DefaultDefinition(**{**d, "custom_sql_predicate": "DPD >= 30   AND  past_due_amount > 1000"})
    assert definition_version(p1) == definition_version(p2)


def test_apply_without_confirmation_or_approval_is_refused(lake, cfg_dir, definition_yaml):
    from lau.pipeline import definition_ops as ops

    changed = definition_yaml({"delinquency_threshold_dpd": 120})
    with pytest.raises(ops.ApprovalRequiredError):
        ops.apply(changed, confirm=None, run_cycle=False, log=lambda m: None)


# ---- (c) no stage reads a label not tagged with the active version ----------------------------------------
def test_c_stages_read_only_active_version_labels(lake, cfg_dir, definition_yaml):
    from lau.definition import labels_io
    from lau.definition.registry import active_version
    from lau.pipeline import definition_ops as ops
    from lau.store import get_store

    v1 = lake["version"]
    changed = definition_yaml({"delinquency_threshold_dpd": 60})
    labels_io.READ_LOG.clear()
    res = ops.apply(changed, confirm=lambda q: True, run_cycle=False, log=lambda m: None)
    v2 = res["version"]
    try:
        st = get_store("harness")
        assert active_version(st) == v2
        assert labels_io.READ_LOG, "pipeline must read labels through labels_io"
        for r in labels_io.READ_LOG:
            assert r.requested_version == v2 and r.active_version == v2, r
            assert r.returned_versions in ((v2,), ()), r
            assert not r.allow_inactive, r
        # both versions coexist in storage; reading the old one without opt-in fails
        with pytest.raises(labels_io.LabelVersionError):
            labels_io.read_labels(st, v1, "test.stale_reader")
    finally:  # restore the 90 DPD definition for other tests
        ops.apply(cfg_dir / "default_definition.yaml", confirm=lambda q: True, run_cycle=False, log=lambda m: None)
    assert active_version(get_store("harness")) == v1


def test_c_labels_tables_referenced_only_by_sanctioned_modules():
    """Static guard: only the label writer/reader modules (and view DDL) touch label tables directly."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "lau"
    allowed = {
        "definition/labels_io.py",
        "pipeline/stages.py",
        "harness/holdout.py",
        "promotion/monitor.py",
        "cli.py",
    }  # cli.check-access deliberately queries holdout AS THE AGENT to prove it is denied
    offenders = []
    for f in src.rglob("*.py"):
        rel = f.relative_to(src).as_posix()
        text = f.read_text()
        if ("'labels_all'" in text or "'oot_labels'" in text) and rel not in allowed:
            offenders.append(rel)
    assert not offenders, offenders


# ---- (d) different definitions -> different labels on the same data --------------------------------------
def test_d_two_definitions_produce_different_labels(synth_small, cfg_dir):
    d90 = _base(cfg_dir)
    d60 = d90.model_copy(update={"delinquency_threshold_dpd": 60})
    apps = synth_small.applications
    loans = apps[apps["approved"]][["loan_id", "application_id", "origination_month", "decision_ts"]]
    l90 = build_labels(synth_small.performance, loans, d90, "2026-06")
    l60 = build_labels(synth_small.performance, loans, d60, "2026-06")
    assert l90["definition_version"].iloc[0] != l60["definition_version"].iloc[0]
    both = l90.merge(l60, on="loan_id", suffixes=("_90", "_60")).dropna(subset=["label_90", "label_60"])
    flips = (both["label_90"] != both["label_60"]).sum()
    assert flips > 0
    # monotone: every 90+ DPD default is also a 60+ DPD default (same everything else, 'ever' timing)
    assert ((both["label_90"] == 1) & (both["label_60"] == 0)).sum() == 0
    assert label_summary(l60)["default_rate"] > label_summary(l90)["default_rate"]


def test_materiality_and_window_timing_change_labels(synth_small, cfg_dir):
    base = _base(cfg_dir)
    apps = synth_small.applications
    loans = apps[apps["approved"]][["loan_id", "application_id", "origination_month", "decision_ts"]]
    r = {
        n: label_summary(build_labels(synth_small.performance, loans, d, "2026-06"))["n_default"]
        for n, d in {
            "base": base,
            "no_materiality": base.model_copy(update={"balance_materiality_threshold": 0.0}),
            "end_of_window": base.model_copy(update={"delinquency_timing": "end_of_window"}),
        }.items()
    }
    assert r["no_materiality"] > r["base"]  # planted short payers with trivial past-due balances
    assert r["end_of_window"] < r["base"]  # cures before window end are not defaults at window end


def test_censor_rule_keeps_immature_loans_flagged(synth_small, cfg_dir):
    d = _base(cfg_dir).model_copy(update={"maturity_rule": "censor", "min_seasoning_months": 3})
    apps = synth_small.applications
    loans = apps[apps["approved"]][["loan_id", "application_id", "origination_month", "decision_ts"]]
    lab = build_labels(synth_small.performance, loans, d, "2026-06")
    assert lab["is_censored"].sum() > 0
    assert not lab.loc[lab["is_censored"], "is_excluded"].any()


# ---- (e) the old champion is never compared with challengers of another definition --------------------------
def test_e_no_cross_definition_champion_comparison(lake, cfg_dir, definition_yaml):
    from lau.data.features import load_dev_frame
    from lau.harness.evaluate import evaluate_model
    from lau.modeling import registry_io
    from lau.modeling.model import PDModel
    from lau.modeling.search_space import defaults
    from lau.pipeline import definition_ops as ops
    from lau.store import get_store

    st = get_store("harness")
    v1 = lake["version"]
    dev1 = load_dev_frame(st, v1, "test")
    tr1 = dev1[dev1["split"] == "train"]
    feats = ["bureau_score", "dti", "util_revolving", "inq_6m", "pmt_to_income"]
    m1 = PDModel("logreg", defaults("logreg"), feats, [], v1).fit(tr1, tr1["label"].to_numpy())
    _, mv1 = registry_io.log_candidate(m1, {}, {"author": "test"}, tr1, role="harness")
    # register it as the v1 champion directly in the production registry
    with registry_io.mlflow_session("promoter") as c:
        try:
            c.create_registered_model(registry_io.production_model_name())
        except Exception:  # noqa: BLE001
            pass
        pv = c.copy_model_version(registry_io.candidate_uri(mv1), registry_io.production_model_name())
        c.set_model_version_tag(registry_io.production_model_name(), pv.version, "definition_version", v1)
        c.set_model_version_tag(registry_io.production_model_name(), pv.version, "lau_kind", "champion")
        c.set_registered_model_alias(registry_io.production_model_name(), registry_io.champion_alias(v1), pv.version)

    changed = definition_yaml({"delinquency_threshold_dpd": 60})
    v2 = ops.apply(changed, confirm=lambda q: True, run_cycle=False, log=lambda m: None)["version"]
    try:
        # 1. a v1 model cannot be evaluated under v2 at all
        with pytest.raises(registry_io.DefinitionMismatchError):
            evaluate_model(m1, v2, "test:v1-model", count_test=False)
        # 2. a v2 challenger is compared with the v2 reference (baseline), never the v1 champion
        dev2 = load_dev_frame(st, v2, "test")
        tr2 = dev2[dev2["split"] == "train"]
        m2 = PDModel("logreg", defaults("logreg"), feats, [], v2).fit(tr2, tr2["label"].to_numpy())
        ev = evaluate_model(m2, v2, "test:v2-model", count_test=False)
        assert ev["reference"]["kind"] == "baseline"
        assert registry_io.champion_for(v2) is None
        # 3. old champion kept, tagged superseded
        tags = registry_io.version_tags(registry_io.production_model_name(), pv.version, "harness")
        assert tags.get("superseded_by_definition_change") == "true"
        # 4. a mis-pointed alias is detected
        with registry_io.mlflow_session("promoter") as c:
            c.set_registered_model_alias(
                registry_io.production_model_name(), registry_io.champion_alias(v2), pv.version
            )
        with pytest.raises(registry_io.DefinitionMismatchError):
            registry_io.champion_for(v2)
        with registry_io.mlflow_session("promoter") as c:
            c.delete_registered_model_alias(registry_io.production_model_name(), registry_io.champion_alias(v2))
    finally:
        ops.apply(cfg_dir / "default_definition.yaml", confirm=lambda q: True, run_cycle=False, log=lambda m: None)


# ---- sandbox ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        "dpd >= (SELECT max(dpd) FROM x)",
        "dpd >= 90; DROP TABLE t",
        "read_csv('/etc/passwd') IS NOT NULL",
        "labels.label = 1",
        "some_unknown_column > 1",
        "*",
    ],
)
def test_custom_predicate_sandbox_rejects(bad):
    with pytest.raises(UnsafeExpressionError):
        normalize_predicate(bad)


def test_cure_rule_cured_loan_is_not_default():
    """A loan that hits 90 DPD at mob 4 and is then current for 8 months is cured under cured_not_default."""
    import pandas as pd

    rows = []
    for mob in range(1, 13):
        dpd = {2: 30, 3: 60, 4: 90}.get(mob, 0)
        rows.append(
            {
                "loan_id": "L1",
                "application_id": "A1",
                "mob": mob,
                "status": "delinquent" if dpd else "current",
                "dpd": dpd,
                "balance": 1000.0,
                "past_due_amount": 300.0 if dpd else 0.0,
                "scheduled_payment": 100.0,
                "payment_amount": 100.0,
                "charge_off_flag": 0,
                "bankruptcy_flag": 0,
                "settlement_flag": 0,
                "forbearance_flag": 0,
                "payoff_flag": 0,
                "fraud_flag": 0,
                "deceased_flag": 0,
            }
        )
    perf = pd.DataFrame(rows)
    loans = pd.DataFrame(
        [
            {
                "loan_id": "L1",
                "application_id": "A1",
                "origination_month": "2024-01",
                "decision_ts": pd.Timestamp("2024-01-05"),
            }
        ]
    )
    base = DefaultDefinition(delinquency_threshold_dpd=90, observation_window_months=12)
    cured = base.model_copy(update={"cure_handling": {"mode": "cured_not_default", "cure_months_required": 3}})
    assert build_labels(perf, loans, base, "2026-06")["label"].iloc[0] == 1
    assert build_labels(perf, loans, DefaultDefinition(**cured.model_dump()), "2026-06")["label"].iloc[0] == 0
