"""Real-time decisioning on the local lake: policy approvals, the decision engine, the served model's parity with
training, synthetic traffic and the decision log, shadow-first rollouts, release checks, adverse-action content.

Nothing here touches Databricks or creates an endpoint: the in-process transport decides with the same registered
artifact the endpoint would serve.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
import yaml


# ---- helpers ---------------------------------------------------------------------------------------------------------
def _policy_dict() -> dict:
    from lau.decision.policy import load_policy

    return load_policy().model_dump()


class FakeModel:
    """PDModel-like: fixed PD, fixed contributions; can fail or be slow."""

    def __init__(self, p: float, fail: bool = False, sleep_s: float = 0.0) -> None:
        self.p, self.fail, self.sleep_s, self.seen = p, fail, sleep_s, None

    def predict_pd(self, df: pd.DataFrame) -> np.ndarray:
        self.seen = df
        if self.fail:
            raise KeyError("missing model inputs: ['bur_attr_001']")
        time.sleep(self.sleep_s)
        return np.full(len(df), self.p)

    def contributions(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = {
            "dti": 0.9,
            "cf_nsf_count_6m": 0.6,
            "cf_overdraft_txn_count_6m": 0.5,
            "pmt_to_income": 0.4,
            "scheduled_payment": 0.35,  # same statement as pmt_to_income: listed once
            "zz_mystery_feature": 0.3,
            "bureau_score": -0.8,  # pushes toward approval: never a reason
        }
        return pd.DataFrame({k: [v] * len(df) for k, v in cols.items()}, index=df.index)


def _request(rid: str = "rq-T1", **app) -> dict:
    base = {"application_id": "T1", "dti": 0.30, "bureau_score": 700, "legacy_score": 600, "annual_income": 60000}
    lines = [
        {"txn_date": "2026-07-10", "amount": 2500.0, "balance_after": 3000.0, "category": "income"},
        {"txn_date": "2026-07-20", "amount": -900.0, "balance_after": 2100.0, "category": "housing"},
        {"txn_date": "2026-08-12", "amount": 2400.0, "balance_after": 4500.0, "category": "income"},
    ]
    return {"request_id": rid, "application": {**base, **app}, "transactions": lines, "decision_date": "2026-09-01"}


VERSIONS = {"model_version": "3", "policy_version": "p1", "build_id": "b1"}


# ---- engine --------------------------------------------------------------------------------------------------------
def test_knockouts_decline_before_any_model_is_consulted(lake):
    from lau.decision import engine

    model = FakeModel(0.01)
    out = engine.decide([_request(dti=0.80)], model, _policy_dict(), VERSIONS)[0]
    assert (out["decision"], out["path"]) == ("decline", "knockout")
    assert [r["code"] for r in out["reasons"]] == ["R03"] and out["probability_of_default"] is None
    low = engine.decide([_request(bureau_score=500)], model, _policy_dict(), VERSIONS)[0]
    assert (low["decision"], low["reasons"][0]["code"]) == ("decline", "R01")
    thin = engine.decide([_request(bureau_score=None)], model, _policy_dict(), VERSIONS)[0]
    assert thin["path"] == "model"  # thin files are scored, not knocked out


def test_pd_maps_to_decision_and_band_under_the_policy(lake):
    from lau.decision import engine

    pol = _policy_dict()
    for p, decision, band in [(0.03, "approve", "A"), (0.14, "refer", "D"), (0.40, "decline", "E")]:
        out = engine.decide([_request()], FakeModel(p), pol, VERSIONS)[0]
        assert (out["decision"], out["risk_band"], out["path"]) == (decision, band, "model")
        assert (out["reasons"] == []) == (decision == "approve")


def test_adverse_decisions_carry_up_to_four_distinct_mapped_reasons(lake):
    from lau.decision import engine

    out = engine.decide([_request()], FakeModel(0.40), _policy_dict(), VERSIONS)[0]
    codes = [r["code"] for r in out["reasons"]]
    assert codes == ["R03", "R13", "R14", "R02"]  # pmt_to_income and scheduled_payment share R02: listed once
    assert all(r["mapped"] for r in out["reasons"]) and not out["reasons_missing"]


def test_without_a_serving_model_the_legacy_policy_decides(lake):
    from lau.decision import engine

    ok = engine.decide([_request(legacy_score=600)], None, _policy_dict(), VERSIONS)[0]
    no = engine.decide([_request(legacy_score=400)], None, _policy_dict(), VERSIONS)[0]
    assert (ok["decision"], ok["path"], ok["fallback_used"]) == ("approve", "legacy", False)
    assert (no["decision"], no["reasons"][0]["code"]) == ("decline", "R01")


def test_a_failing_or_slow_model_falls_back_to_the_legacy_policy_and_says_so(lake):
    from lau.decision import engine

    failed = engine.decide([_request()], FakeModel(0.1, fail=True), _policy_dict(), VERSIONS)[0]
    assert (failed["path"], failed["fallback_used"]) == ("legacy", True)
    assert "missing model inputs" in failed["fallback_reason"]
    slow = engine.decide([_request()], FakeModel(0.1, sleep_s=0.5), _policy_dict(), VERSIONS, timeout_ms=50)[0]
    assert (slow["path"], slow["fallback_used"]) == ("legacy", True) and slow["fallback_reason"].startswith("timeout")


def test_decision_ids_are_deterministic_and_repeats_are_decided_once(lake):
    from lau.decision import engine

    pol = _policy_dict()
    a = engine.decide([_request()], FakeModel(0.05), pol, VERSIONS)[0]
    b = engine.decide([_request()], FakeModel(0.05), pol, VERSIONS)[0]
    assert a["decision_id"] == b["decision_id"]
    changed = engine.decide([_request(dti=0.31)], FakeModel(0.05), pol, VERSIONS)[0]
    assert changed["decision_id"] != a["decision_id"]  # same request id, different payload: a different decision
    twice = engine.decide([_request(), _request("rq-T2"), _request()], FakeModel(0.05), pol, VERSIONS)
    assert twice[0] is twice[2] and len({d["decision_id"] for d in twice}) == 2


def test_submitted_cashflow_features_and_post_decision_lines_are_ignored(lake):
    from lau.decision import engine

    req = _request(cf_nsf_count_6m=0.0)  # a client cannot supply its own cash-flow features
    req["transactions"] += [
        {"txn_date": "2026-08-20", "amount": -40.0, "balance_after": -15.0, "category": "nsf_fee"},
        {"txn_date": "2026-09-01", "amount": -35.0, "balance_after": -50.0, "category": "nsf_fee"},  # decision day
        {"txn_date": "2026-09-15", "amount": -35.0, "balance_after": -85.0, "category": "nsf_fee"},  # after it
    ]
    frame = engine.request_frame([req])
    assert frame["cf_nsf_count_6m"].iloc[0] == 1  # only the line strictly before the decision date counts
    assert frame["cf_months_observed"].iloc[0] == 2


def test_served_cashflow_features_equal_the_training_features(lake):
    """Parity by construction: the served path runs the curate stage's SQL and summariser on submitted lines."""
    from lau.decision import engine, traffic
    from lau.store import get_store
    from lau.synth.cashflow import CASHFLOW_FEATURES

    st = get_store("harness")
    raw = st.query(f"SELECT * FROM {st.fq('raw', 'new_applications_raw')} ORDER BY application_id LIMIT 150")
    ids = ", ".join(f"'{a}'" for a in raw["application_id"])
    tx = st.query(
        f"SELECT * FROM {st.fq('raw', 'bank_transactions')} "
        f"WHERE application_id IN ({ids}) AND days_before_decision >= 1"
    )
    curated = st.query(f"SELECT * FROM {st.fq('curated', 'new_applications')} WHERE application_id IN ({ids})")
    curated = curated.set_index("application_id").loc[raw["application_id"]]
    served = engine.request_frame(traffic.build_requests(raw, tx)).set_index("application_id")
    pd.testing.assert_frame_equal(
        served[CASHFLOW_FEATURES].astype(float), curated[CASHFLOW_FEATURES].astype(float), check_names=False
    )


# ---- policy versions and approvals -----------------------------------------------------------------------------------
def test_policy_changes_need_the_required_number_of_different_approvers(lake, tmp_path, monkeypatch, cfg_dir):
    from lau.decision import policy
    from lau.settings import get_settings

    base = yaml.safe_load((cfg_dir / "policy.yaml").read_text())
    renamed = {**base, "name": "renamed only"}
    assert policy.policy_version(policy.Policy(**renamed)) == policy.policy_version(policy.Policy(**base))
    stricter = {**base, "decision": {"approve_max_pd": 0.10, "refer_max_pd": 0.15}}
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(stricter))
    before = policy.active()
    monkeypatch.setitem(get_settings().thresholds.setdefault("approvals", {}), "policy", {"dev": 2})
    plan = policy.plan(path)
    assert not plan["is_noop"] and {d["field"] for d in plan["diff"]} >= {"decision"}
    with pytest.raises(policy.PolicyNotActiveError, match="0 of 2"):
        policy.apply(path)
    v = policy.record_approval(policy.load_policy(path), "alice", "cut-offs checked")
    policy.record_approval(policy.load_policy(path), "alice", "again")  # the same person never counts twice
    assert policy.approvers(v) == ["alice"]
    with pytest.raises(policy.PolicyNotActiveError, match="1 of 2"):
        policy.apply(path)
    policy.record_approval(policy.load_policy(path), "bob", "independent review")
    try:
        assert policy.apply(path, by="bob")["changed"] and policy.active()[0] == v
        assert not policy.apply(path, by="bob")["changed"]
    finally:
        if before is not None:
            monkeypatch.setitem(get_settings().thresholds["approvals"], "policy", {"dev": 1})
            policy.apply(cfg_dir / "policy.yaml")  # back to the policy the other tests use


def test_invalid_policies_are_rejected(cfg_dir):
    from lau.decision.policy import Policy

    base = yaml.safe_load((cfg_dir / "policy.yaml").read_text())
    with pytest.raises(ValueError, match="refer_max_pd"):
        Policy(**{**base, "decision": {"approve_max_pd": 0.2, "refer_max_pd": 0.1}})
    with pytest.raises(ValueError, match="bands"):
        Policy(**{**base, "bands": {"A": 0.1, "B": 0.05, "C": 1.0}})


# ---- build, traffic, log, rollouts (one shared setup) ---------------------------------------------------------------
@pytest.fixture(scope="module")
def decisioning(lake, cfg_dir):
    """An approved policy, two production champions (v_a serving), small traffic settings."""
    from lau.data.features import load_dev_frame
    from lau.decision import policy
    from lau.definition.registry import active_version
    from lau.modeling import registry_io
    from lau.modeling.model import PDModel
    from lau.modeling.search_space import defaults
    from lau.settings import get_settings
    from lau.store import get_store

    st = get_store("harness")
    version = active_version(st)
    dev = load_dev_frame(st, version, "test")
    train = dev[dev["split"] == "train"]
    prod = registry_io.production_model_name()
    feats = {
        "a": ["bureau_score", "dti", "util_revolving", "inq_6m", "pmt_to_income"],
        "b": ["bureau_score", "dti", "util_revolving", "pmt_to_income", "cf_nsf_count_6m", "cf_income_cv_6m"],
    }
    versions = {}
    for key, cols in feats.items():
        model = PDModel("logreg", defaults("logreg"), cols, [], version).fit(train, train["label"].to_numpy())
        _, mv = registry_io.log_candidate(model, {}, {"author": "test"}, train, role="harness")
        with registry_io.mlflow_session("promoter") as c:
            try:
                c.create_registered_model(prod)
            except Exception:  # noqa: BLE001, S110 - exists
                pass
            pv = c.copy_model_version(registry_io.candidate_uri(mv), prod)
            c.set_model_version_tag(prod, pv.version, "definition_version", version)
            c.set_model_version_tag(prod, pv.version, "lau_kind", "champion")
        versions[key] = str(pv.version)
    with registry_io.mlflow_session("promoter") as c:
        c.set_registered_model_alias(prod, registry_io.SERVING_ALIAS, versions["a"])
    p = policy.load_policy(cfg_dir / "policy.yaml")
    policy.record_approval(p, "alice", "initial policy reviewed")
    policy.apply(cfg_dir / "policy.yaml", by="alice")
    s = get_settings()
    saved = json.loads(json.dumps(s.decisioning))
    s.decisioning["traffic"]["applications_per_month"] = 120
    s.decisioning["rollout"]["min_shadow_decisions"] = 50
    yield {"version": version, **versions}
    s.decisioning.clear()
    s.decisioning.update(saved)


def _decisions() -> pd.DataFrame:
    from lau.store import get_store

    st = get_store("harness")
    return st.query(f"SELECT * FROM {st.fq('ops', 'decisions')}")


def test_build_registers_a_live_decision_model_and_is_idempotent(decisioning):
    from lau.decision import build

    first = build.build(log=lambda m: None)
    v = first["versions"]
    assert v["model_version"] == decisioning["a"] and v["shadow_model_version"] is None and v["policy_version"]
    again = build.build(log=lambda m: None)
    assert not again["changed"] and again["version"] == build.live()[0]
    status = build.status()
    assert status["gaps"] == [] and status["serving_model_version"] == decisioning["a"]


def test_originate_decides_a_simulated_month_and_logs_every_decision_once(decisioning):
    from lau.decision import build, traffic
    from lau.decision import log as decision_log
    from lau.store import get_store

    build.build(log=lambda m: None)
    month = traffic.current_month()
    out = traffic.originate(months=1, kind="inprocess", log=lambda m: None)
    assert out["transport"] == "inprocess" and out["months"][0]["decisions"] == 120
    assert traffic.current_month() == month + 1
    d = _decisions()
    mine = d[d["application_id"].str.startswith(f"M{month.year % 100:02d}{month.month:02d}")]
    assert len(mine) == 120 and mine["decision_id"].is_unique
    assert set(mine["model_version"]) == {decisioning["a"]} and mine["policy_version"].notna().all()
    assert set(mine["decision"]) <= {"approve", "refer", "decline"} and not mine["is_test"].any()
    adverse = mine[mine["decision"] == "decline"]
    assert (adverse["reason_codes"].str.len() > 0).all()
    st = get_store("harness")
    inputs = st.query(f"SELECT * FROM {st.fq('curated', 'decision_inputs')}")
    assert set(mine["decision_id"]) <= set(inputs["decision_id"])
    truth = st.query(f"SELECT * FROM {st.fq('ops', 'sim_truth')} WHERE sim_month = '{month}'")
    assert len(truth) == 120  # latent risk for the servicer simulator; never in a request
    one = inputs[inputs["decision_id"] == mine["decision_id"].iloc[0]].iloc[0]
    assert "latent_risk" not in json.loads(one["application_json"])
    # logging the same decisions again adds nothing
    again = mine.head(3)[["decision_id", "request_id"]].to_dict("records")
    assert decision_log.record(again, source="test") == 0


def test_a_promotion_scores_in_shadow_until_its_rollout_is_approved_and_served(decisioning):
    from lau.console import actions
    from lau.decision import build, rollout, traffic
    from lau.modeling import registry_io

    r = rollout.start(decisioning["b"], decisioning["version"], promotion_id="promo-test", by="alice")
    assert rollout.shadow_version() == decisioning["b"]
    build.build(log=lambda m: None)
    assert build.live()[1]["shadow_model_version"] == decisioning["b"]
    traffic.originate(months=1, kind="inprocess", log=lambda m: None)
    d = _decisions()
    shadowed = d[d["shadow_model_version"] == decisioning["b"]]
    assert len(shadowed) == 120 and set(shadowed["model_version"]) == {decisioning["a"]}  # b decides nothing yet
    report = rollout.report(r["rollout_id"])
    assert (
        report["n"] == 120
        and 0 <= report["agreement"] <= 1
        and set(report["serving"]) == {"approve", "refer", "decline"}
    )

    blocked = actions.rollout_serve(r["rollout_id"], "alice")
    assert not blocked["ok"] and "0 of 1" in blocked["message"]
    assert not actions.rollout_decide(r["rollout_id"], "approve", "short", "alice")["ok"]
    assert actions.rollout_decide(r["rollout_id"], "approve", "shadow report reviewed: agreement fine", "alice")["ok"]
    served = actions.rollout_serve(r["rollout_id"], "alice")
    assert served["ok"], served["message"]
    assert registry_io.serving_model("harness")["model_version"] == decisioning["b"]
    assert rollout.get(r["rollout_id"])["state"] == "serving" and rollout.shadow_version() is None
    live = build.live()[1]
    assert (live["model_version"], live["shadow_model_version"]) == (decisioning["b"], "")

    from lau.decision import checks

    drill = checks.rollback(n=40, log=lambda m: None)
    assert drill["passed"] and drill["restores"] == f"v{decisioning['a']}"

    assert not actions.rollout_rollback(r["rollout_id"], "", "bob")["ok"]  # a rollback needs a reason
    back = actions.rollout_rollback(r["rollout_id"], "drill: confirm one-step rollback", "bob")
    assert back["ok"] and registry_io.serving_model("harness")["model_version"] == decisioning["a"]
    assert rollout.get(r["rollout_id"])["state"] == "rolled_back"
    assert build.live()[1]["model_version"] == decisioning["a"]


def test_a_newer_promotion_supersedes_a_rollout_still_in_shadow(decisioning):
    from lau.decision import rollout

    first = rollout.start(decisioning["b"], decisioning["version"], None, by="alice")
    second = rollout.start(decisioning["b"], decisioning["version"], None, by="alice")
    assert rollout.get(first["rollout_id"])["state"] == "superseded"
    assert rollout.in_state("shadow")["rollout_id"] == second["rollout_id"]
    rollout._event(second, "cancelled", "superseded", "test", "cleanup")


def test_parity_and_load_checks_pass_in_process(decisioning):
    from lau.decision import build, checks

    build.build(log=lambda m: None)
    parity = checks.parity(n=120, log=lambda m: None)
    assert parity["passed"], parity
    assert parity["max_feature_gap"] == 0 and parity["max_pd_gap"] is not None and parity["max_pd_gap"] <= 1e-6
    load = checks.load(n=40, concurrency=2, kind="inprocess", log=lambda m: None)
    assert load["errors"] == 0 and load["transport"] == "inprocess" and load["p95_ms"] is not None
    tests = _decisions()
    assert tests[tests["request_id"].str.startswith("lt-")]["is_test"].all()


def test_adverse_action_content_for_a_logged_decline(decisioning):
    from lau.decision.notices import notice

    d = _decisions()
    declined = d[(d["decision"] == "decline") & ~d["is_test"]]
    assert len(declined)
    n = notice(str(declined["decision_id"].iloc[0]))
    assert n["notice_required"] and 1 <= len(n["principal_reasons"]) <= 4
    assert all(set(r) == {"rank", "code", "statement"} for r in n["principal_reasons"])  # no feature names
    assert n["versions"]["policy_version"] and notice("dec-does-not-exist") is None


def test_inference_table_rows_parse_into_decisions():
    from lau.decision.log import parse_inference_rows

    pred = {"decision_id": "dec-1", "request_id": "rq-1", "application_id": "A1", "decision": "approve"}
    df = pd.DataFrame(
        [
            {
                "status_code": 200,
                "request": json.dumps({"dataframe_records": [{"request_id": "rq-1"}]}),
                "response": json.dumps({"predictions": [pred]}),
            },
            {
                "status_code": 200,
                "request": json.dumps({"dataframe_split": {"columns": ["request_id"], "data": [["rq-2"]]}}),
                "response": json.dumps({"predictions": [{**pred, "decision_id": "dec-2", "request_id": "rq-2"}]}),
            },
            {"status_code": 503, "request": "{}", "response": None},
        ]
    )
    responses, requests = parse_inference_rows(df)
    assert [r["decision_id"] for r in responses] == ["dec-1", "dec-2"]
    assert [r["request_id"] for r in requests] == ["rq-1", "rq-2"]


def test_policy_approval_needs_a_person_at_a_terminal(lake, cfg_dir, tmp_path):
    from typer.testing import CliRunner

    from lau.cli import app

    base = yaml.safe_load((cfg_dir / "policy.yaml").read_text())
    other = {**base, "knockouts": {"max_dti": 0.6, "min_bureau_score": 560}}
    (tmp_path / "policy.yaml").write_text(yaml.safe_dump(other))
    from lau.decision import policy

    original = policy.POLICY_PATH
    policy.POLICY_PATH = tmp_path / "policy.yaml"
    try:
        res = CliRunner().invoke(app, ["policy", "approve", "--note", "scripted"])
    finally:
        policy.POLICY_PATH = original
    assert res.exit_code == 1 and "interactive terminal" in res.output


def test_engine_handles_requests_without_statements(lake):
    from lau.decision import engine
    from lau.synth.cashflow import CASHFLOW_FEATURES

    req = {"request_id": "rq-none", "application": {"application_id": "N1", "dti": 0.2, "legacy_score": 700}}
    model = FakeModel(0.05)
    out = engine.decide([req], model, _policy_dict(), VERSIONS)[0]
    assert out["decision"] == "approve" and out["decision_date"] == datetime.now(UTC).date().isoformat()
    assert all(c in model.seen.columns and model.seen[c].isna().all() for c in CASHFLOW_FEATURES)


# ---- the console's view ----------------------------------------------------------------------------------------------
@pytest.fixture
def console(decisioning, monkeypatch):
    from fastapi.testclient import TestClient

    from lau.console.app import create_app
    from lau.console.util import clear_cache
    from lau.decision import build, checks, traffic
    from lau.evidence.run import run_all

    build.build(log=lambda m: None)
    traffic.originate(months=2, kind="inprocess", log=lambda m: None)  # this test's own traffic and checks
    checks.parity(n=60, log=lambda m: None)
    checks.load(n=20, concurrency=2, kind="inprocess", log=lambda m: None)
    run_all(log=lambda m: None, only="model_registry")  # the console reads the serving alias from the registry mirror
    monkeypatch.setenv("LAU_CONSOLE_ACTIONS", "1")
    clear_cache()
    yield TestClient(create_app())
    clear_cache()


def test_console_shows_live_decisions_policy_and_api_state(console, decisioning):
    d = console.get("/api/decisions").json()
    assert (
        d["available"]
        and d["totals"]["n"] >= 240
        and abs(sum(d["shares"][k] for k in ("approve", "refer", "decline")) - 1) < 1e-3  # shares are rounded
    )
    assert d["policy"]["approve_max_pd"] == 0.12 and d["policy"]["approvers"]
    assert d["api"]["state"] == "in_process" and d["api"]["live_build"]["version"]
    assert {c["check"] for c in d["api"]["checks"]} >= {"parity", "load"}
    assert all(not r["decision_id"].startswith("lt-") for r in d["recent"])
    one = d["recent"][0]["decision_id"]
    detail = console.get(f"/api/decisions/{one}").json()
    assert detail["decision_id"] == one and "application_json" not in detail  # never applicant inputs
    found = console.get("/api/decisions/search", params={"q": d["recent"][0]["application_id"]}).json()["results"]
    assert any(r["decision_id"] == one for r in found)
    assert console.get("/api/decisions/dec-unknown").status_code == 404
    assert console.get("/api/decisions/bad id!").status_code == 400
    status = console.get("/api/status").json()
    assert status["api"]["live"] and status["api"]["label"] == "Deciding in process"


def test_console_adverse_action_content_has_no_feature_names(console):
    d = console.get("/api/decisions").json()
    declines = [r for r in d["recent"] if r["decision"] == "decline"]
    assert declines
    n = console.get(f"/api/decisions/{declines[0]['decision_id']}/adverse-action").json()
    assert n["notice_required"] and "for_reviewers" not in n
    assert all(set(r) == {"rank", "code", "statement"} for r in n["principal_reasons"])


def test_console_rollout_actions_follow_the_rules(console, decisioning):
    from lau.decision import rollout

    r = rollout.start(decisioning["b"], decisioning["version"], None, by="alice")
    try:
        view = console.get("/api/rollouts").json()
        mine = next(x for x in view["rollouts"] if x["rollout_id"] == r["rollout_id"])
        assert mine["state"] == "shadow" and mine["approvals"]["required"] == 1
        bad = console.post(f"/api/rollouts/{r['rollout_id']}/decide", json={"decision": "maybe", "note": "x" * 20})
        assert bad.status_code == 400
        assert console.post("/api/rollouts/ro-nope/serve").status_code == 404
        serve = console.post(f"/api/rollouts/{r['rollout_id']}/serve").json()
        assert not serve["ok"] and "shadow decisions" in serve["message"]  # no shadow traffic for this one yet
        short = console.post(f"/api/rollouts/{r['rollout_id']}/rollback", json={"reason": "no"})
        assert short.status_code == 400
    finally:
        rollout._event(r, "cancelled", "superseded", "test", "cleanup")
