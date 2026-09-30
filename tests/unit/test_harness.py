"""Evaluation harness: metrics, leakage detection on planted data, multiple testing, holdout isolation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lau.harness import metrics
from lau.harness.multiple_testing import required_margin

CAUSAL = ["bureau_score", "dti", "util_revolving", "inq_6m", "pmt_to_income"]


def test_metrics_basic():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 5000)
    p = np.clip(0.3 * y + rng.random(5000) * 0.7, 0, 1)
    assert 0.5 < metrics.auc(y, p) <= 1
    assert 0 < metrics.ks(y, p) <= 1
    assert metrics.psi(p, p) < 1e-6
    assert metrics.psi(p, p + 0.5) > 0.25
    lift = metrics.lift_by_decile(y, p)
    assert lift["default_rate"].iloc[0] >= lift["default_rate"].iloc[-1]


def test_high_cardinality_categorical_does_not_fake_high_auc():
    rng = np.random.default_rng(1)
    x = pd.Series([f"z{i}" for i in rng.integers(0, 900, 5000)])
    y = rng.integers(0, 2, 5000)
    assert metrics.univariate_auc(x, y) < 0.6  # out-of-fold encoding: noise stays noise


def test_multiple_testing_margin_grows_and_resets_per_version(lake):
    from lau.harness import multiple_testing as mt
    from lau.store import get_store

    cfg = {"base_auc_margin": 0.002, "mt_penalty_k": 0.003}
    margins = [required_margin(n, cfg) for n in (0, 1, 5, 20, 100)]
    assert margins == sorted(margins) and margins[0] == pytest.approx(0.002)
    st = get_store("harness")
    before = mt.n_tests(st, lake["version"])
    mt.record(st, lake["version"], "test:x")
    assert mt.n_tests(st, lake["version"]) == before + 1
    assert mt.n_tests(st, "some-other-version") == 0


def test_catalog_flags_planted_leak_and_proxy_and_finds_signal(lake):
    from lau.store import get_store

    st = get_store("harness")
    cat = st.query(f"SELECT * FROM {st.fq('curated', 'data_catalog')} WHERE definition_version = '{lake['version']}'")
    risk = dict(zip(cat["variable"], cat["leakage_risk"], strict=True))
    proxy = dict(zip(cat["variable"], cat["proxy_risk"], strict=True))
    assert risk["acct_review_flag"] == "high"  # planted post-decision leak
    assert proxy["geo_affluence_idx"] == "high"  # planted protected-class proxy
    assert risk["zip3"] != "high"  # high-cardinality field must not look like a leak
    clean = cat[(cat["leakage_risk"] != "high")].sort_values("univariate_auc_train", ascending=False)
    # payment components (loan_amount, scheduled_payment, income) and the legacy score legitimately rank high too
    top = set(clean.head(12)["variable"])
    assert len(top & set(CAUSAL)) >= 4, top


def _fit(lake, feats, model_type="logreg"):
    from lau.data.features import load_dev_frame
    from lau.modeling.model import PDModel
    from lau.modeling.search_space import defaults
    from lau.store import get_store

    dev = load_dev_frame(get_store("harness"), lake["version"], "test")
    tr = dev[dev["split"] == "train"]
    return PDModel(model_type, defaults(model_type), feats, [], lake["version"]).fit(
        tr, tr["label"].to_numpy(), tr["es_tail"].to_numpy()
    )


def test_harness_catches_planted_leakage(lake):
    from lau.harness.evaluate import evaluate_model

    m = _fit(lake, [*CAUSAL, "acct_review_flag"], "lightgbm")
    ev = evaluate_model(m, lake["version"], "test:leaky", count_test=False)
    leak = {x["column"]: x for x in ev["leakage"]}
    assert leak["acct_review_flag"]["risk"] == "high"
    assert ev["checks"]["no_leakage"] is False and ev["passed_validation"] is False


def test_harness_catches_proxy_and_prohibited(lake):
    from lau.harness.evaluate import evaluate_model

    m = _fit(lake, [*CAUSAL, "geo_affluence_idx"])
    ev = evaluate_model(m, lake["version"], "test:proxy", count_test=False)
    assert "geo_affluence_idx" in ev["proxies_flagged"]
    assert ev["checks"]["no_proxy_features"] is False


def test_clean_model_evaluation_structure(lake):
    from lau.harness.evaluate import evaluate_model

    m = _fit(lake, CAUSAL)
    ev = evaluate_model(m, lake["version"], "test:clean", count_test=False)
    for k in (
        "validation",
        "lift",
        "calibration_table",
        "time_slices",
        "segments",
        "fairness",
        "reason_code_quality",
        "reference",
        "checks",
        "required_margin",
    ):
        assert k in ev
    assert ev["checks"]["no_leakage"] and ev["checks"]["no_proxy_features"]
    assert ev["reason_code_quality"]["coverage_any"] >= 0.99
    assert ev["validation"]["auc"] > 0.65


# ---- holdout isolation --------------------------------------------------------------------------------------
def test_agent_role_denied_on_holdout_and_restricted_schemas(lake):
    from lau.store import AccessDeniedError, get_store

    agent = get_store("agent")
    for sql in [
        f"SELECT * FROM {agent.fq('holdout', 'oot_labels')}",
        f"SELECT * FROM {agent.fq('labels', 'labels_all')}",
        f"SELECT * FROM {agent.fq('raw', 'protected_attributes')}",
        f"SELECT * FROM {agent.fq('raw', 'performance')}",
        f"SELECT * FROM {agent.fq('ops', 'approvals')}",
        f"SELECT * FROM {agent.fq('curated', 'applications')}",  # only the dev view is granted
        f"SELECT a.* FROM {agent.fq('curated', 'applications_dev')} a JOIN {agent.fq('holdout', 'oot_labels')} h "
        "ON a.application_id = h.application_id",
        f"INSERT INTO {agent.fq('production', 'promotions')} SELECT 1",
    ]:
        with pytest.raises(AccessDeniedError):
            agent.query(sql)
    ok = agent.query(f"SELECT count(*) AS n FROM {agent.fq('labels', 'labels_active')}")
    assert int(ok["n"].iloc[0]) > 0


def test_agent_sees_only_train_labels_of_active_version(lake):
    from lau.definition.labels_io import LabelVersionError, read_labels
    from lau.store import get_store

    agent = get_store("agent")
    tr = read_labels(agent, lake["version"], "test.agent", splits=("train",))
    assert set(tr["split"]) == {"train"}
    with pytest.raises(LabelVersionError):
        read_labels(agent, lake["version"], "test.agent", splits=("train", "validation"))


def test_holdout_requires_gate_token(lake):
    from lau.harness.holdout import HoldoutAccessError, HoldoutToken, read_holdout
    from lau.store import get_store

    with pytest.raises(HoldoutAccessError):
        HoldoutToken(object(), "sneaky", "x")
    with pytest.raises(HoldoutAccessError):
        read_holdout(get_store("harness"), lake["version"], token="not-a-token")  # type: ignore[arg-type]


def test_promotion_gate_uses_holdout_and_budget(lake):
    from lau.harness.gate import holdout_uses, promotion_gate
    from lau.store import get_store

    st = get_store("harness")
    before = holdout_uses(st, lake["version"])
    g = promotion_gate(_fit(lake, CAUSAL), lake["version"], "test:gate")
    assert "holdout" in g and g["holdout"]["n"] > 0
    assert holdout_uses(st, lake["version"]) == before + 1


def test_engineered_feature_train_register_evaluate_roundtrip(lake):
    """Regression: candidates using registered engineered features must register (MLflow input example) and score."""
    from lau.data.feature_registry import register_feature
    from lau.harness.evaluate import evaluate_model
    from lau.modeling import registry_io
    from lau.modeling.train import train_model
    from lau.store import get_store

    agent = get_store("agent")
    cols = agent.query(f"SELECT * FROM {agent.fq('curated', 'applications_dev')} LIMIT 0").columns.tolist()
    register_feature(agent, "loan_to_income_t", "loan_amount / nullif(annual_income, 0)", "leverage", "higher -> PD up",
                     "test", "cy-test", cols, lake["version"])
    model, df, _ = train_model(agent, lake["version"], "logreg", {}, CAUSAL, ["loan_to_income_t"], consumer="test")
    _, mv = registry_io.log_candidate(model, {}, {"author": "test"}, df, role="harness")
    loaded = registry_io.load_pd_model(registry_io.candidate_uri(mv), "harness")
    assert "loan_to_income_t" in loaded.features
    ev = evaluate_model(loaded, lake["version"], f"candidate:{mv}", count_test=False)
    assert ev["checks"]["no_leakage"]
