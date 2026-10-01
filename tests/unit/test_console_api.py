"""Console API: every endpoint answers in the contract's shape, reads only through the ui role, and gates actions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pandas as pd
import pytest

CYCLE = "cy-test-console"
VERDICTS = {"improved", "no_change", "not_best", "regressed", "insufficient_evidence"}

# Top-level keys of each response type in console/web/src/api/types.ts
SHAPES = {
    "/status": {
        "generated_at",
        "environment",
        "data_mode",
        "backend",
        "active_definition",
        "yaml_definition_version",
        "yaml_matches_active",
        "serving",
        "serving_superseded",
        "verdict",
        "activity",
        "budget",
        "decisions_waiting",
        "alerts_open",
        "api",
        "feed",
        "actions_enabled",
        "user",
    },
    "/overview": {"status_sentence", "tiles", "waiting", "recent_events", "pipeline"},
    "/activity": {"cycle", "last_cycle", "pipeline"},
    "/decisions": {
        "available",
        "reason",
        "window_days",
        "as_of",
        "totals",
        "shares",
        "latency",
        "daily",
        "paths",
        "versions",
        "bands",
        "reasons",
        "recent",
        "policy",
        "api",
    },
    "/progress": {
        "verdict",
        "benchmark",
        "reference_diffs",
        "best_known_diffs",
        "lineage",
        "guardrails",
        "process_health",
        "denominator",
        "production",
    },
    "/events": {"events", "next_before"},
    "/definitions/sensitivity": {"computed_at", "series"},
    "/pipeline": {"definition_version", "stages", "runs"},
    "/upcoming": {"jobs", "queue", "next_plan", "waiting", "forecast", "backlog"},
    "/performance": {"definition_version", "definitions", "evaluations", "ledger", "holdout"},
    "/fairness": {
        "definition_version",
        "threshold_air",
        "approval_rate",
        "candidates",
        "proxy_heatmap",
        "proxy_threshold",
        "prohibited_features",
        "findings",
    },
    "/feed": {"live", "reason", "requires", "performance", "vintage", "maturation"},
    "/catalog": {"definition_version", "definitions", "variables"},
    "/cashflow/cohorts": {"computed_at", "cohorts"},
    "/lessons": {"active_definition", "lessons"},
    "/approvals": {"pending", "history", "actions_enabled"},
    "/rollouts": {"available", "reason", "rollouts", "min_shadow_decisions", "required_approvals", "promotions"},
    "/shadow": {"available", "reason", "runs", "distributions", "agreement_at_policy"},
    "/alerts": {"available", "reason", "alerts", "monitoring_runs"},
    "/cost": {
        "month_to_date_usd",
        "hard_stop_usd",
        "cycle_caps",
        "by_day",
        "by_cycle",
        "by_agent",
        "pricing",
        "billing_available",
    },
    "/settings": {
        "thresholds",
        "budgets",
        "models",
        "benchmarks",
        "protected_classes",
        "config_versions",
        "access_checks",
        "notifications",
    },
}
LISTS = ["/cycles", "/models", "/definitions", "/features", "/agents", "/reports"]


@pytest.fixture(scope="module")
def client(lake):
    """The console app over the test lake, with evidence computed and a live cycle and an alert planted."""
    from fastapi.testclient import TestClient

    from lau.console.app import create_app
    from lau.console.util import clear_cache
    from lau.evidence.run import run_all
    from lau.store import get_store

    run_all(log=lambda m: None)
    st = get_store("harness")
    now = datetime.now(UTC)
    v = lake["version"]
    planted = {
        "cycles": pd.DataFrame(
            [
                {
                    "cycle_id": CYCLE,
                    "definition_version": v,
                    "reason": "console test",
                    "started_at": now - timedelta(minutes=3),
                    "status": "running",
                    "summary_json": "{}",
                }
            ]
        ),
        "cycle_heartbeat": pd.DataFrame(
            [
                {
                    "ts": now - timedelta(minutes=1),
                    "cycle_id": CYCLE,
                    "step": "feature",
                    "agent": "feature",
                    "state": "running",
                    "experiments_used": 0,
                    "spent_usd": 0.12,
                }
            ]
        ).astype({"experiments_used": "int32"}),
        "agent_trace": pd.DataFrame(
            [
                {
                    "ts": now - timedelta(minutes=2),
                    "cycle_id": CYCLE,
                    "definition_version": v,
                    "agent": "feature",
                    "principal": "agent",
                    "action": "propose_feature",
                    "state_changing": True,
                    "inputs": json.dumps({"name": "x_ratio"}),
                    "outputs": json.dumps({"feature_id": "f-1"}),
                    "cost_usd": 0.0,
                    "status": "ok",
                }
            ]
        ),
        "alerts": pd.DataFrame(
            [{"kind": "psi", "subject": "score", "value": 0.31, "severity": "high", "ts": now, "definition_version": v}]
        ),
        "monitoring_runs": pd.DataFrame(
            [
                {
                    "ts": now,
                    "definition_version": v,
                    "summary_json": json.dumps({"score_psi": 0.31, "max_feature_psi": 0.2, "alerts": [{}]}),
                }
            ]
        ),
    }
    for table, df in planted.items():
        st.write_df("ops", table, df, mode="append")
    clear_cache()
    yield TestClient(create_app())
    admin = get_store("admin")
    for table in ("cycles", "cycle_heartbeat", "agent_trace", "cycle_control"):
        if admin.table_exists("ops", table):
            admin.execute(f"DELETE FROM {admin.fq('ops', table)} WHERE cycle_id = '{CYCLE}'")
    for table in ("alerts", "monitoring_runs", "alert_acks"):
        if admin.table_exists("ops", table):
            admin.execute(f"DROP TABLE {admin.fq('ops', table)}")
    clear_cache()


def _get(client, path: str, **params):
    r = client.get("/api" + path, params=params)
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    return r.json()


@pytest.mark.parametrize("path", sorted(SHAPES))
def test_endpoint_matches_contract_shape(client, path):
    body = _get(client, path)
    assert SHAPES[path] <= set(body), SHAPES[path] - set(body)


@pytest.mark.parametrize("path", LISTS)
def test_list_endpoints_return_lists(client, path):
    assert isinstance(_get(client, path), list)


def test_responses_never_contain_nan(client):
    for path in [*SHAPES, *LISTS]:
        assert "NaN" not in client.get("/api" + path).text, path


def test_detail_endpoints_resolve_from_their_lists(client):
    models = _get(client, "/models")
    assert models
    m = models[0]["model"]
    name = quote(m["name"], safe="")
    card = _get(client, f"/models/{name}/{m['version']}")
    assert card["model"]["key"] == m["key"]
    lineage = _get(client, f"/lineage/{name}/{m['version']}")
    assert any(n["type"] == "model" for n in lineage["nodes"])
    assert all({"from", "to"} <= set(e) for e in lineage["edges"])
    d = _get(client, "/definitions")[0]
    assert _get(client, f"/definitions/{d['short']}")["version"] == d["version"]  # short prefixes resolve
    assert {"summary", "dpd", "timing", "window_months"} <= set(d)
    evaluations = _get(client, "/performance")["evaluations"]
    assert evaluations
    detail = _get(client, f"/evaluations/{evaluations[0]['eval_id']}")
    assert {"validation", "lift", "calibration", "fairness", "checks"} <= set(detail)
    var = _get(client, "/catalog")["variables"][0]["variable"]
    assert _get(client, f"/catalog/{var}")["variable"] == var
    cycle = _get(client, f"/cycles/{CYCLE}")
    assert {"plan", "steps", "reports", "trace", "report_markdown"} <= set(cycle)
    assert client.get("/api/models/nope/1").status_code == 404
    assert client.get("/api/definitions/zzzzzzzz").status_code == 404


def test_status_and_activity_show_the_live_cycle(client):
    s = _get(client, "/status")
    assert s["activity"]["state"] == "cycle_running" and s["activity"]["cycle_id"] == CYCLE
    assert s["actions_enabled"] is False
    live = _get(client, "/activity")["cycle"]
    assert live["cycle_id"] == CYCLE and live["state"] == "running"
    lanes = {lane["role"]: lane for lane in live["lanes"]}
    assert lanes["feature"]["state"] == "running" and lanes["planner"]["state"] == "pending"
    trace = _get(client, "/activity/trace", cycle_id=CYCLE)
    assert [t["kind"] for t in trace] == ["proposed"]  # a feature proposal is an agent claim, not a measurement
    assert _get(client, "/activity/trace", cycle_id=CYCLE, after=trace[-1]["ts"]) == []


def test_progress_reads_the_benchmark_ledger(client):
    p = _get(client, "/progress")
    assert p["verdict"]["code"] in VERDICTS
    b = p["benchmark"]
    assert any(r["model"]["kind"] == "reference" for r in b["rows"])
    assert b["primary_definition"] in {d["key"] for d in b["definitions"]}
    for d in p["reference_diffs"] + p["best_known_diffs"]:
        assert d["diff"]["lo"] <= d["diff"]["estimate"] + 1e-12 <= d["diff"]["hi"] + 2e-12
    assert p["production"]["available"] is False  # no decision API yet: no production evidence claimed


def test_events_are_typed_sorted_and_paginate(client):
    from lau.console.services.events import EVENT_TYPES

    everything = _get(client, "/events", limit=500)["events"]
    ids = [e["id"] for e in everything]
    assert len(ids) == len(set(ids))  # ids are unique: they break timestamp ties in the cursor
    stamps = [e["ts"] for e in everything]
    assert stamps == sorted(stamps, reverse=True)
    assert all(e["type"] in EVENT_TYPES for e in everything)
    # walking the pages with the cursor returns every event exactly once, even when timestamps tie at a boundary
    walked, before = [], None
    while True:
        page = _get(client, "/events", limit=3, **({"before": before} if before else {}))
        walked += [e["id"] for e in page["events"]]
        before = page["next_before"]
        if not before:
            break
    assert walked == ids
    only = _get(client, "/events", types="evaluation")
    assert {e["type"] for e in only["events"]} <= {"evaluation"}
    assert client.get("/api/events", params={"definition": "zzzzzzzz"}).status_code == 404
    assert client.get("/api/events", params={"before": "not a time"}).status_code == 400


def test_alert_ids_follow_the_contract(client):
    a = _get(client, "/alerts")["alerts"][0]
    assert {"current", "title", "ack_at", "ack_note"} <= set(a) and a["current"] is True
    want = hashlib.sha256(f"{pd.Timestamp(a['ts']).isoformat()}|{a['kind']}|{a['subject']}".encode()).hexdigest()
    assert a["id"] == want[:12]


def test_actions_are_refused_unless_enabled(client):
    posts = [
        ("/activity/stop", {"cycle_id": CYCLE, "reason": "x"}),
        ("/approvals/candidate:1/gate", None),
        ("/approvals/candidate:1/decision", {"decision": "approve", "rationale": "long enough rationale"}),
        ("/approvals/candidate:1/promote", None),
        ("/alerts/abcdef012345/ack", {"note": ""}),
    ]
    for path, body in posts:
        assert client.post("/api" + path, json=body).status_code == 403, path


def test_stop_and_acknowledge_when_actions_are_enabled(client, monkeypatch):
    monkeypatch.setenv("LAU_CONSOLE_ACTIONS", "1")
    r = client.post("/api/activity/stop", json={"cycle_id": CYCLE, "reason": "console test"})
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert _get(client, "/activity")["cycle"]["state"] == "stopping"
    alert = _get(client, "/alerts")["alerts"][0]
    r = client.post(f"/api/alerts/{alert['id']}/ack", json={"note": "seen"})
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert next(a for a in _get(client, "/alerts")["alerts"] if a["id"] == alert["id"])["acknowledged"]
    bad = client.post("/api/approvals/candidate:1/decision", json={"decision": "maybe", "rationale": ""})
    assert bad.status_code == 400


def test_ui_role_cannot_read_applicant_level_data(lake):
    from lau.store import get_store

    ui = get_store("ui")
    for schema, table in [
        ("curated", "applications"),
        ("curated", "cashflow_monthly"),
        ("labels", "labels_all"),
        ("holdout", "oot_labels"),
        ("raw", "performance"),
    ]:
        with pytest.raises(PermissionError):
            ui.query(f"SELECT * FROM {ui.fq(schema, table)} LIMIT 1")
    assert len(ui.query(f"SELECT * FROM {ui.fq('curated', 'data_catalog')} LIMIT 1")) == 1


def test_ask_needs_a_key_and_row_level_scores_stay_aggregate(client, monkeypatch):
    import lau.credentials as credentials
    from lau.console.ask import check_aggregate_only

    monkeypatch.setattr(credentials, "has_anthropic_key", lambda: False)
    assert client.post("/api/ask", json={"question": "Is the system improving?"}).status_code == 503
    assert client.post("/api/ask", json={"question": ""}).status_code == 400
    with pytest.raises(PermissionError):
        check_aggregate_only("SELECT application_id, pd FROM lending_uw_dev.ops.shadow_scores")
    check_aggregate_only("SELECT role, avg(pd) AS mean_pd FROM lending_uw_dev.ops.shadow_scores GROUP BY role")


def test_evidence_packet_uses_registry_names_and_reports_budget(client):
    ev = _get(client, "/performance")["evaluations"]
    ref = ev[0]["candidate_ref"]  # the test lake has baseline evaluations only (no cycles run)
    packet = _get(client, f"/approvals/{quote(ref, safe='')}")
    names = {m["model"]["name"] for m in _get(client, "/models")}
    assert packet["model"]["name"] in names  # links to /models/<name>/<version> resolve
    assert {"decision", "promotion", "holdout"} <= set(packet)
    assert packet["holdout"]["budget"] >= packet["holdout"]["used"] >= 0


def test_search_links_to_console_routes(client):
    assert _get(client, "/search", q="a") == []  # too short
    hits = _get(client, "/search", q="bureau")
    assert hits and len(hits) <= 30 and all(h["href"].startswith("/") for h in hits)


def test_verdict_is_flagged_stale_when_newer_harness_facts_exist(client):
    from lau.console.util import clear_cache
    from lau.store import get_store

    assert _get(client, "/progress")["verdict"]["stale_reason"] is None  # evidence was just computed
    admin = get_store("admin")
    dv = admin.query(f"SELECT * FROM {admin.fq('ops', 'data_version')} ORDER BY created_at DESC LIMIT 1")
    dv["data_version"] = "stale-check"
    dv["created_at"] = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)
    admin.write_df("ops", "data_version", dv, mode="append")
    clear_cache()
    try:
        reason = _get(client, "/progress")["verdict"]["stale_reason"]
        assert reason and "a data load" in reason
        assert _get(client, "/status")["verdict"]["stale"] is True
    finally:
        admin.execute(f"DELETE FROM {admin.fq('ops', 'data_version')} WHERE data_version = 'stale-check'")
        clear_cache()
