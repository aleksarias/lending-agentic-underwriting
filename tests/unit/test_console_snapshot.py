"""Console snapshot and mirror, two-person rule, and the actions the local console runs."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pandas as pd
import pytest
import yaml


class _CountingVolume:
    """Wraps a LocalVolume and counts table uploads."""

    def __init__(self, inner) -> None:
        self.inner, self.table_writes = inner, 0

    def read(self, rel: str):
        return self.inner.read(rel)

    def write(self, rel: str, data: bytes) -> None:
        if rel.startswith("tables/"):
            self.table_writes += 1
        self.inner.write(rel, data)


@pytest.fixture
def mirror_store(tmp_path):
    """A second, empty local lake standing in for the laptop's mirror."""
    from lau.settings import Settings
    from lau.store import LocalStore

    old = os.environ.get("LAU_LOCAL_LAKE")
    os.environ["LAU_LOCAL_LAKE"] = str(tmp_path / "mirror")
    try:
        store = LocalStore("admin", Settings())
    finally:
        os.environ["LAU_LOCAL_LAKE"] = old or ""
    return store, tmp_path / "mirror"


def test_snapshot_round_trip_through_the_mirror(lake, tmp_path, mirror_store):
    from lau.console.snapshot import LocalVolume, Mirror, publish
    from lau.store import get_store

    vol = LocalVolume(tmp_path / "vol")
    manifest = publish(source="test", log_fn=lambda m: None, ui_store=get_store("ui"), volume=vol)
    tables = set(manifest["tables"])
    assert "curated.data_catalog" in tables and "labels.split_meta" in tables
    # only what the ui role can read: never raw data, all-version labels, applicant rows or the holdout
    assert not any(t.startswith(("raw.", "holdout.")) for t in tables)
    assert not tables & {"labels.labels_all", "curated.applications", "curated.cashflow_monthly"}

    counting = _CountingVolume(vol)
    publish(source="test", log_fn=lambda m: None, ui_store=get_store("ui"), volume=counting)
    assert counting.table_writes == 0  # unchanged tables are not uploaded again

    target, directory = mirror_store
    m = Mirror(volume=vol, target=lambda: target, directory=directory)
    first = m.sync_once()
    assert set(first["changed"]) == tables
    src = get_store("ui").query(f"SELECT count(*) AS n FROM {get_store('ui').fq('curated', 'data_catalog')}")
    dst = target.query(f"SELECT count(*) AS n FROM {target.fq('curated', 'data_catalog')}")
    assert int(src["n"].iloc[0]) == int(dst["n"].iloc[0]) > 0
    assert m.sync_once()["changed"] == []  # nothing new published


def test_live_cycle_overlays_the_mirror(lake, tmp_path, mirror_store):
    from lau.console.snapshot import LocalVolume, Mirror, publish_live

    vol = LocalVolume(tmp_path / "vol")
    now = datetime.now(UTC).isoformat()
    cycle = {"cycle_id": "cy-live-test", "definition_version": lake["version"], "reason": "test", "started_at": now}
    beats = [{"ts": now, "cycle_id": "cy-live-test", "step": "feature", "agent": "feature", "state": "running",
              "experiments_used": 1, "spent_usd": 0.2}]  # fmt: skip
    trace = [{"ts": now, "cycle_id": "cy-live-test", "definition_version": lake["version"], "agent": "feature",
              "principal": "agent", "action": "propose_feature", "state_changing": True, "inputs": "{}",
              "outputs": "{}", "cost_usd": 0.0, "status": "ok"}]  # fmt: skip
    publish_live({**cycle, "status": "running"}, beats, trace, volume=vol)
    target, directory = mirror_store
    assert Mirror(volume=vol, target=lambda: target, directory=directory).sync_once()["live"] is True
    cycles = target.query(f"SELECT status FROM {target.fq('ops', 'cycles')} WHERE cycle_id = 'cy-live-test'")
    assert list(cycles["status"]) == ["running"]
    n = target.query(f"SELECT count(*) AS n FROM {target.fq('ops', 'agent_trace')} WHERE cycle_id = 'cy-live-test'")
    assert int(n["n"].iloc[0]) == 1


def test_next_quartz_run_for_daily_and_weekly_schedules():
    from lau.console.snapshot import next_quartz_run

    at = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)  # a Wednesday
    assert next_quartz_run("0 0 6 * * ?", at) == datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    assert next_quartz_run("0 30 18 * * ?", at) == datetime(2026, 9, 30, 18, 30, tzinfo=UTC)
    assert next_quartz_run("0 0 7 ? * MON", at) == datetime(2026, 10, 5, 7, 0, tzinfo=UTC)
    assert next_quartz_run("0 0/5 * * * ?", at) is None  # anything fancier is not guessed


@pytest.fixture
def two_approvers():
    from lau.settings import get_settings

    cfg = get_settings().thresholds.setdefault("approvals", {}).setdefault("promotion", {})
    old = cfg.get("dev")
    cfg["dev"] = 2
    yield
    cfg["dev"] = old if old is not None else 1


def _plant_gate(ref: str, version: str, passed: bool = True) -> str:
    from lau.store import get_store

    gate_id = f"gate-test-{ref.replace(':', '-')}"
    result = {"gate_id": gate_id, "candidate_ref": ref, "definition_version": version, "passed": passed}
    get_store("harness").write_df(
        "ops",
        "gate_results",
        pd.DataFrame(
            [
                {
                    "gate_id": gate_id,
                    "candidate_ref": ref,
                    "definition_version": version,
                    "ts": datetime.now(UTC),
                    "passed": passed,
                    "holdout_auc": 0.73,
                    "reference_holdout_auc": 0.63,
                    "result_json": json.dumps(result),
                }
            ]
        ),
        mode="append",
    )
    return gate_id


def test_two_person_rule_on_promotion_decisions(lake, two_approvers):
    from lau.console import actions
    from lau.governance.approvals import required, tally
    from lau.promotion.promote import gate_decisions
    from lau.store import get_store

    ref = "candidate:991"
    gate_id = _plant_gate(ref, lake["version"])
    assert required("promotion") == 2
    first = actions.decide(ref, "approve", "evidence reviewed, looks sound", "alice")
    assert first["ok"] and "1 of 2" in first["message"]
    again = actions.decide(ref, "approve", "approving a second time", "alice")
    assert not again["ok"] and "already recorded" in again["message"]
    second = actions.decide(ref, "approve", "independent second review done", "bob")
    assert second["ok"] and "can now be promoted" in second["message"]
    counts = tally(gate_decisions(get_store("harness"), ref, gate_id))
    assert counts["count"] == 2 and counts["approvers"] == ["alice", "bob"]
    assert not actions.decide(ref, "approve", "too short", "carol")["ok"]  # rationale under 10 characters


def test_two_person_rule_on_definition_changes(lake, cfg_dir, definition_yaml):
    from lau.definition import registry
    from lau.pipeline import definition_ops as ops
    from lau.pipeline.definition_ops import ApprovalRequiredError
    from lau.settings import get_settings
    from lau.store import get_store

    cfg = get_settings().thresholds.setdefault("approvals", {}).setdefault("definition", {})
    old = cfg.get("dev")
    cfg["dev"] = 2
    try:
        changed = definition_yaml({"delinquency_threshold_dpd": 150})  # a definition no other test approves
        version = ops.plan(changed, with_impact=False).version
        with pytest.raises(ApprovalRequiredError, match="1 of 2"):
            ops.apply(changed, confirm=lambda q: True, run_cycle=False, log=lambda m: None)
        st = get_store("harness")
        assert len(registry.approvers(st, version)) == 1
        registry.record_approval(st, version, "second review", approver=registry.approvers(st, version)[0])
        assert len(registry.approvers(st, version)) == 1  # the same person approving again does not count twice
    finally:
        cfg["dev"] = old if old is not None else 1
        st = get_store("admin")
        st.execute(f"DELETE FROM {st.fq('ops', 'definition_approvals')} WHERE definition_version = '{version}'")


def test_cli_actions_print_one_json_result(lake):
    from typer.testing import CliRunner

    from lau.cli import app

    ref = "candidate:992"
    _plant_gate(ref, lake["version"])
    out = CliRunner().invoke(
        app,
        ["decide", ref, "--decision", "approve", "--rationale", "reviewed on the cli", "--approver", "dana", "--json"],
    )
    assert out.exit_code == 0, out.output
    result = json.loads(out.output.strip().splitlines()[-1])
    assert result["ok"] and result["ref"].startswith("apr-")
    bad = CliRunner().invoke(app, ["decide", ref, "--decision", "maybe", "--rationale", "x" * 12, "--json"])
    assert bad.exit_code == 1 and json.loads(bad.output.strip().splitlines()[-1])["ok"] is False


def test_mirror_mode_runs_actions_through_the_cli(monkeypatch):
    from lau.console import actions

    seen: list[list[str]] = []
    monkeypatch.setenv("LAU_CONSOLE_MIRROR", "1")
    monkeypatch.setattr(
        actions, "run_cli", lambda args, timeout_s=1800: seen.append(args) or {"ok": True, "message": "ok"}
    )
    actions.dispatch(
        "decide", candidate_ref="candidate:7", decision="approve", rationale="looks good to me", approver="eve"
    )
    actions.dispatch("ack", alert_id="abc123def456", note="seen", by="eve")
    assert seen[0][:2] == ["decide", "candidate:7"] and "--approver" in seen[0]
    assert seen[1][:2] == ["ack-alert", "abc123def456"]


def test_console_previews_and_approves_a_definition_change(lake, cfg_dir, monkeypatch):
    from fastapi.testclient import TestClient

    from lau.console.app import create_app
    from lau.console.util import clear_cache
    from lau.definition import registry
    from lau.store import get_store

    path = cfg_dir / "default_definition.yaml"
    original = path.read_text()
    monkeypatch.setenv("LAU_CONSOLE_ACTIONS", "1")
    client = TestClient(create_app())
    try:
        clear_cache()
        assert client.get("/api/definitions/proposal").json()["proposal"] is None  # the YAML is the active one
        changed = yaml.safe_load(original)
        changed["balance_materiality_threshold"] = 37.5  # a change no other test uses: its approval is removed below
        path.write_text(yaml.safe_dump(changed))
        clear_cache()
        p = client.get("/api/definitions/proposal").json()["proposal"]
        assert p and {d["field"] for d in p["diff"]} == {"balance_materiality_threshold"} and p["approvers"] == []
        assert any(r["stage"] == "labels" for r in p["rebuilds"])
        wrong = client.post("/api/definitions/0123456789ab/approve", json={"note": "checked the plan carefully"}).json()
        assert not wrong["ok"] and "exact hash" in wrong["message"]
        ok = client.post(f"/api/definitions/{p['version']}/approve", json={"note": "checked the plan carefully"}).json()
        assert ok["ok"], ok
        again = client.post(
            f"/api/definitions/{p['version']}/approve", json={"note": "checked the plan carefully"}
        ).json()
        assert not again["ok"] and "already approved" in again["message"]
        assert len(registry.approvers(get_store("harness"), p["version"])) == 1
    finally:
        path.write_text(original)
        clear_cache()
        st = get_store("harness")
        if st.table_exists("ops", "definition_approvals"):
            st.execute(
                f"DELETE FROM {st.fq('ops', 'definition_approvals')} WHERE plan_summary = 'checked the plan carefully'"
            )
