"""Closing the loop on the local lake: the simulated servicer's feed, ingestion with expectations and quarantine, the
bitemporal history and restatements, production labels and maturation, and the production evidence steps."""

from __future__ import annotations

import json

import pandas as pd
import pytest

MONTHS = 15  # the test definition's window is 12 months: loans of the first months mature


@pytest.fixture(scope="module")
def fed(decision_stack):
    """Fifteen simulated months of synthetic traffic, each followed by the servicer's feed and its ingestion."""
    from lau.decision import build, traffic
    from lau.feedback import feed, production, servicer
    from lau.settings import get_settings

    s = get_settings()
    saved = json.loads(json.dumps({"d": s.decisioning, "f": s.feedback}))
    s.decisioning["traffic"]["applications_per_month"] = 80
    s.feedback["servicer"].update(misreport_rate=0.05, malformed_rate=0.02)  # enough of both to check
    build.build(log=lambda m: None)
    first = traffic.current_month()
    events = []
    for _ in range(MONTHS):
        traffic.originate(months=1, kind="inprocess", log=lambda m: None)
        servicer.run(log=lambda m: None)
        feed.ingest(log=lambda m: None)
        events.append(production.maturation_check(log=lambda m: None))
    yield {"first": first, "last": traffic.current_month() - 1, "events": events, **decision_stack}
    s.decisioning.clear()
    s.decisioning.update(saved["d"])
    s.feedback.clear()
    s.feedback.update(saved["f"])


def _q(table: str, key: str = "curated", where: str = "") -> pd.DataFrame:
    from lau.store import get_store

    st = get_store("harness")
    if not st.table_exists(key, table):
        return pd.DataFrame(columns=["kind", "status", "severity", "value"])
    return st.query(f"SELECT * FROM {st.fq(key, table)} {where}")


# ---- expectations ---------------------------------------------------------------------------------------------------
GOOD = {
    "record_type": "status",
    "loan_id": "L1",
    "period_month": "2026-08",
    "status": "current",
    "dpd": 0,
    "balance": 1000.0,
    "past_due_amount": 0.0,
    "payment_amount": 50.0,
    **{
        f: 0
        for f in (
            "charge_off_flag",
            "bankruptcy_flag",
            "settlement_flag",
            "forbearance_flag",
            "payoff_flag",
            "fraud_flag",
            "deceased_flag",
        )
    },
}


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({}, None),
        ({"loan_id": None}, "loan_id missing"),
        ({"loan_id": "L999"}, "never booked"),
        ({"status": "in_review"}, "not a known status"),
        ({"dpd": 45}, "30-day bucket"),
        ({"balance": -1.0}, "balance must be zero or more"),
        ({"period_month": "2026-13"}, "not YYYY-MM"),
        ({"period_month": "2026-10"}, "after the file's month"),
        ({"record_type": "correction"}, "earlier month"),
        ({"fraud_flag": 2}, "fraud_flag must be 0 or 1"),
        ({"record_type": "rumour"}, "unknown record_type"),
    ],
)
def test_feed_expectations(change, reason):
    from lau.feedback.feed import check

    why = check({**GOOD, **change}, "2026-08" if change.get("record_type") == "correction" else "2026-09", {"L1"})
    if reason is None:
        assert why == []
    else:
        assert any(reason in w for w in why), why


# ---- the servicer and the feed -------------------------------------------------------------------------------------
def test_every_completed_month_has_exactly_one_feed_file_and_all_are_read(fed):
    from lau.feedback import feed, servicer

    runs = _q("feed_runs", "simulation")
    assert runs["reported_month"].is_unique and str(fed["last"]) in set(runs["reported_month"])
    assert feed.pending_files() == [] and feed.held_files() == []
    again = servicer.run(log=lambda m: None)
    assert again["written"] == []  # the feed is written once per month
    files = _q("feed_files", "ops")
    assert set(files["status"]) == {"ingested"} and files["feed_file"].is_unique


def test_bookings_follow_approvals_take_up_and_referrals(fed):
    loans = _q("loan_bookings")
    dec = _q("decisions", "ops").set_index("decision_id")
    assert loans["loan_id"].is_unique and len(loans) > 0
    outcomes = dec.loc[loans["decision_id"], "decision"]
    assert set(outcomes) <= {"approve", "refer"}  # declines never book
    approved = dec[(dec["decision"] == "approve") & ~dec["is_test"]]
    booked_share = (loans["approved_as"] == "approve").sum() / len(
        approved[approved["application_id"].isin(_q("truth", "simulation")["application_id"])]
    )
    assert 0.7 < booked_share <= 1.0  # take-up 85%


def test_malformed_records_are_quarantined_with_reasons(fed):
    q = _q("feed_quarantine", "ops")
    assert len(q) > 0 and q["reasons"].str.len().gt(0).all()
    assert {"loan_id missing", "unparseable JSON"} & {r.split(";")[0] for r in q["reasons"]}
    hist = _q("loan_performance_history")
    assert (
        hist["loan_id"].notna().all()
        and (hist["balance"] >= 0).all()
        and hist["dpd"].isin([0, 30, 60, 90, 120, 150, 180]).all()
    )


def test_corrections_restate_history_without_losing_what_was_known(fed):
    from lau.feedback.feed import as_known_at

    restated = _q("feed_restatements", "ops")
    assert len(restated) > 0
    r = restated.iloc[0]
    truth = _q(
        "performance", "simulation", f"WHERE loan_id = '{r['loan_id']}' AND period_month = '{r['period_month']}'"
    )
    current = _q(
        "loan_performance_current",
        "curated",
        f"WHERE loan_id = '{r['loan_id']}' AND period_month = '{r['period_month']}'",
    )
    assert int(current["dpd"].iloc[0]) == int(truth["dpd"].iloc[0]) == int(r["dpd_after"])  # corrected to the truth
    month_before = str(pd.Period(r["reported_month"], "M") - 1)
    then = as_known_at(month_before)
    then = then[(then["loan_id"] == r["loan_id"]) & (then["period_month"] == r["period_month"])]
    assert int(then["dpd"].iloc[0]) == int(r["dpd_before"])  # what was known before the correction is kept
    hist = _q(
        "loan_performance_history",
        "curated",
        f"WHERE loan_id = '{r['loan_id']}' AND period_month = '{r['period_month']}'",
    )
    assert set(hist["record_type"]) == {"status", "correction"}  # append-only: both reports are there


def test_a_file_with_too_many_bad_records_is_held_until_a_person_releases_it(fed):
    from lau.feedback import feed

    loan = _q("loan_bookings")["loan_id"].iloc[0]
    month = str(fed["last"])
    good = {**GOOD, "loan_id": loan, "period_month": month, "reported_month": month, "record_seq": 0}
    lines = [json.dumps(good)] + [json.dumps({**good, "status": "in_review", "record_seq": i}) for i in range(1, 5)]
    rel = f"loan_feed/{month}/manual-{month}.jsonl"
    feed.feed_volume().write(rel, ("\n".join(lines) + "\n").encode())
    before = len(_q("loan_performance_history"))
    res = feed.ingest(log=lambda m: None)
    assert res["held"] == [rel] and len(_q("loan_performance_history")) == before
    assert feed.ingest(log=lambda m: None)["files"] == 0  # a held file is not re-read every run
    feed.release(rel, by="alice", log=lambda m: None)
    assert len(_q("loan_performance_history")) == before + 1 and rel not in feed.held_files()


# ---- maturity, labels and production evidence ------------------------------------------------------------------------
def test_loans_mature_under_the_active_definition_and_queue_a_cycle(fed):
    from lau.feedback import production

    lab, version, as_of = production.labels()
    assert version == fed["version"] and as_of == str(fed["last"])
    m = production.matured(lab)
    assert len(m) > 0 and m["label"].isin([0, 1]).all()
    assert (m["months_available"] >= 12).all()  # the 12-month window has passed for every matured loan
    ev = _q("maturation_events", "ops")
    assert ev["matured"].is_monotonic_increasing and ev["matured"].iloc[-1] == len(m)


def test_production_evidence_fairness_and_parity_steps(fed):
    from lau.evidence.run import run_all
    from lau.store import get_store

    counts = run_all(log=lambda m: None, only=["production_evidence", "decision_fairness", "serving_parity"])
    assert all(counts[t] > 0 for t in counts), counts
    st = get_store("harness")
    pe = st.query(f"SELECT * FROM {st.fq('ops', 'production_evidence')}")
    overall = pe[pe["scope"] == "overall"].iloc[-1]
    assert overall["n_matured"] > 0 and 0 <= overall["realized_rate"] <= 1 and overall["predicted_pd"] > 0
    assert set(pe["scope"]) == {"overall", "model", "vintage", "band"}
    fair = st.query(f"SELECT * FROM {st.fq('ops', 'decision_fairness')}")
    assert set(fair["method"]) == {"surname_estimate", "synthetic_truth", "application"}
    est = fair[(fair["method"] == "surname_estimate") & (fair["group"] == "white")]["approval_rate"].iloc[-1]
    true = fair[(fair["method"] == "synthetic_truth") & (fair["group"] == "white")]["approval_rate"].iloc[-1]
    assert abs(est - true) < 0.1  # the estimate is close to the synthetic truth for the largest group
    parity = st.query(f"SELECT * FROM {st.fq('ops', 'serving_parity')}")
    assert {"cf_nsf_count_6m", "bureau_score"} <= set(parity["feature"]) and parity["psi"].notna().any()
    assert parity[parity["feature"] == "bureau_score"]["in_serving_model"].iloc[-1]


def test_simulation_truth_is_out_of_reach_for_agents_and_the_console(fed):
    from lau.store import AccessDeniedError, get_store

    for role in ("agent", "ui", "promoter"):
        st = get_store(role)
        with pytest.raises(AccessDeniedError):
            st.query(f"SELECT * FROM {st.fq('simulation', 'truth')} LIMIT 1")


def test_miscalibrated_production_loans_raise_an_alert_and_a_held_file_does_too(fed):
    from lau.feedback import production
    from lau.settings import get_settings

    lab, _, _ = production.labels()
    dec = _q("decisions", "ops", "WHERE NOT is_test AND probability_of_default IS NOT NULL")
    m = production.matured(lab).merge(dec.drop_duplicates("application_id", keep="last"), on="application_id")
    observed, expected = m["label"].astype(int).mean(), m["probability_of_default"].mean()
    gap = (observed - expected) / expected
    tol = get_settings().thresholds["monitoring"]["default_rate_rel_tol"]
    alerts = _q("alerts", "ops")
    raised = alerts[alerts["kind"] == "production_default_rate"]
    if len(m) >= 100 and abs(gap) > tol:
        assert len(raised) and raised["value"].iloc[-1] == pytest.approx(gap)
        assert (raised["severity"].iloc[-1] == "high") == (abs(gap) > 2 * tol)
    else:
        assert raised.empty
    held_files = _q("feed_files", "ops", "WHERE status = 'held'")
    held = alerts[alerts["kind"] == "feed_held"]
    assert len(held) == len(held_files) and set(held["severity"]) <= {"high"}  # one alert per held file
