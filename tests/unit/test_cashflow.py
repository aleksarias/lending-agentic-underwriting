"""Synthetic v2: bank-statement cash flows — anti-leakage guard, planted signal/leak/proxy, agent access."""

from __future__ import annotations

import numpy as np
import pytest

from lau.synth.cashflow import CASHFLOW_FEATURES


def test_transactions_have_balances_and_post_decision_rows(synth_small):
    tx = synth_small.transactions
    assert {"application_id", "txn_date", "days_before_decision", "amount", "balance_after", "category"} <= set(tx)
    assert (tx["days_before_decision"] < 1).sum() > 0  # post-decision feed exists in RAW...
    first = tx.groupby("application_id").head(1)
    assert first["days_before_decision"].min() >= 1  # ...and every statement starts before the decision
    assert set(tx["category"]) >= {"income", "housing", "groceries", "nsf_fee"}
    assert synth_small.ground_truth["cashflow"]["post_decision_rows_in_raw"] > 0


def test_curated_cashflow_uses_only_pre_decision_transactions(lake):
    """Anti-leakage: every row aggregated into curated.cashflow_monthly has days_before_decision >= 1."""
    from lau.store import get_store

    st = get_store("harness")
    m = st.query(f"SELECT min(month_back) lo, max(month_back) hi FROM {st.fq('curated', 'cashflow_monthly')}")
    assert int(m["lo"].iloc[0]) >= 1 and int(m["hi"].iloc[0]) <= 6
    raw_post = st.query(f"SELECT count(*) n FROM {st.fq('raw', 'bank_transactions')} WHERE days_before_decision < 1")
    assert int(raw_post["n"].iloc[0]) > 0
    # recompute one applicant's month-1 income by hand from pre-decision rows only
    app = st.query(f"SELECT application_id FROM {st.fq('curated', 'cashflow_monthly')} LIMIT 1")["application_id"][0]
    tx = st.query(f"SELECT * FROM {st.fq('raw', 'bank_transactions')} WHERE application_id = '{app}'")
    pre = tx[(tx["days_before_decision"] >= 1) & (tx["days_before_decision"] <= 30)]
    got = st.query(
        f"SELECT income FROM {st.fq('curated', 'cashflow_monthly')} WHERE application_id = '{app}' AND month_back = 1"
    )
    assert got["income"].iloc[0] == pytest.approx(pre.loc[pre["amount"] > 0, "amount"].sum(), rel=1e-6)


def test_cashflow_features_in_curated_and_catalog(lake):
    from lau.store import get_store

    st = get_store("harness")
    apps = st.query(f"SELECT * FROM {st.fq('curated', 'applications')} LIMIT 5")
    assert set(CASHFLOW_FEATURES) <= set(apps.columns)
    cat = st.query(
        f"SELECT variable, leakage_risk, proxy_risk, univariate_auc_train FROM "
        f"{st.fq('curated', 'data_catalog')} WHERE definition_version = '{lake['version']}'"
    )
    risk = dict(zip(cat["variable"], cat["leakage_risk"], strict=True))
    proxy = dict(zip(cat["variable"], cat["proxy_risk"], strict=True))
    assert risk["cf_vendor_risk_score"] == "high"  # planted cash-flow leak (vendor refresh after decision)
    assert proxy["cf_remittance_share_6m"] == "high"  # planted cash-flow proxy
    auc = dict(zip(cat["variable"], cat["univariate_auc_train"], strict=True))
    signal = ["cf_income_cv_6m", "cf_min_balance_6m", "cf_expense_to_income_6m", "cf_verified_to_stated_income"]
    assert np.nanmax([auc[f] for f in signal]) > 0.56  # planted cash-flow signal is detectable
    assert auc["cf_gambling_share_6m"] < 0.56  # not causal


def test_agent_reads_dev_cashflows_only(lake):
    from lau.store import AccessDeniedError, get_store

    agent = get_store("agent")
    n = agent.query(f"SELECT count(*) n FROM {agent.fq('curated', 'cashflow_monthly_dev')}")
    assert int(n["n"].iloc[0]) > 0
    for t in [("raw", "bank_transactions"), ("curated", "cashflow_monthly")]:
        with pytest.raises(AccessDeniedError):
            agent.query(f"SELECT * FROM {agent.fq(*t)} LIMIT 1")
    ids = agent.query(f"SELECT DISTINCT application_id FROM {agent.fq('curated', 'cashflow_monthly_dev')}")
    dev = agent.query(f"SELECT application_id FROM {agent.fq('curated', 'applications_dev')}")
    assert set(ids["application_id"]) <= set(dev["application_id"])  # no holdout-period applicants


def test_cashflow_model_beats_bureau_only(lake):
    """The planted cash-flow signal adds lift beyond the bureau/application causal features."""
    from lau.data.features import load_dev_frame
    from lau.harness.metrics import auc
    from lau.modeling.model import PDModel
    from lau.modeling.search_space import defaults
    from lau.store import get_store

    dev = load_dev_frame(get_store("harness"), lake["version"], "test")
    tr, va = dev[dev["split"] == "train"], dev[dev["split"] == "validation"]
    base = ["bureau_score", "dti", "util_revolving", "inq_6m", "pmt_to_income"]
    cfs = [
        "cf_income_cv_6m",
        "cf_min_balance_6m",
        "cf_expense_to_income_6m",
        "cf_nsf_count_6m",
        "cf_housing_on_time_share_6m",
        "cf_verified_to_stated_income",
    ]
    a = PDModel("logreg", defaults("logreg"), base, [], lake["version"]).fit(tr, tr["label"].to_numpy())
    b = PDModel("logreg", defaults("logreg"), base + cfs, [], lake["version"]).fit(tr, tr["label"].to_numpy())
    assert auc(va["label"], b.predict_pd(va)) > auc(va["label"], a.predict_pd(va)) + 0.01
