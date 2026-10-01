"""Operations plumbing for the console: version ledger, live cycle visibility, stop control, access checks.

Everything runs on the local lake. No test calls Claude: the agent runner is replaced by a fake that returns an
`AgentRunResult`, and nothing here touches Databricks.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml


# ---- helpers ----------------------------------------------------------------------------------------------
def _harness():
    from lau.store import get_store

    return get_store("harness")


def _count(table: str, key: str = "ops") -> int:
    st = _harness()
    if not st.table_exists(key, table):
        return 0
    return int(st.query(f"SELECT count(*) AS n FROM {st.fq(key, table)}")["n"].iloc[0])


def _for_cycle(table: str, cycle_id: str, cols: str = "*") -> pd.DataFrame:
    st = _harness()
    return st.query(f"SELECT {cols} FROM {st.fq('ops', table)} WHERE cycle_id = '{cycle_id}' ORDER BY ts")


def _cycle_row(cycle_id: str) -> pd.DataFrame:
    st = _harness()
    return st.query(
        f"SELECT status, summary_json, started_at FROM {st.fq('ops', 'cycles')} WHERE cycle_id = '{cycle_id}'"
    )


def _edit_yaml(path: Path, edit) -> None:
    doc = yaml.safe_load(path.read_text())
    edit(doc)
    path.write_text(yaml.safe_dump(doc))


# ---- version ledger ---------------------------------------------------------------------------------------
@pytest.fixture
def vdirs(tmp_path, cfg_dir, monkeypatch):
    """Private copies of the config and prompt dirs plus a fixed git state: hashes move only when a test moves them."""
    from lau import versioning

    cfg, prompts = tmp_path / "config", tmp_path / "prompts"
    shutil.copytree(cfg_dir, cfg)
    shutil.copytree(versioning.PROMPTS_DIR, prompts)
    git = {"rev-parse": "a" * 40 + "\n", "status": "", "diff": ""}
    monkeypatch.setattr(versioning, "CONFIG_DIR", cfg)
    monkeypatch.setattr(versioning, "PROMPTS_DIR", prompts)
    monkeypatch.setattr(versioning, "_git", lambda *args: git.get(args[0]))
    return {"config": cfg, "prompts": prompts, "git": git}


def _moved(before: dict, after: dict) -> set[str]:
    return {c for c in after if before.get(c) != after[c]}


def test_current_versions_cover_every_component(vdirs):
    from lau import versioning

    v = versioning.current_versions()
    roles = {p.stem for p in vdirs["prompts"].glob("*.md") if not p.name.startswith("_")}
    assert roles >= {"planner", "profiler", "feature", "modeling", "redteam", "compliance", "curator"}
    assert set(v) == {
        "thresholds",
        "budgets",
        "protected_classes",
        "models",
        "benchmarks",
        "decisioning",
        "reason_statements",
        "feedback",
        "readiness",
        "grants",
        "code",
    } | {f"prompt:{r}" for r in roles}
    for component, (version_hash, content) in v.items():
        if component != "code":
            assert re.fullmatch(r"[0-9a-f]{12}", version_hash), component
        json.loads(content)  # canonical JSON, storable as content_json
    assert v["code"][0] == "a" * 12


def test_hashes_are_stable_and_follow_content(vdirs):
    from lau import versioning

    base = versioning.current_versions()
    assert versioning.current_versions() == base

    thresholds = vdirs["config"] / "thresholds.yaml"
    thresholds.write_text("# only a comment changed\n" + thresholds.read_text())
    assert versioning.current_versions() == base  # YAML is parsed before hashing

    _edit_yaml(thresholds, lambda d: d["gate"].update(max_ece=0.05))
    after = versioning.current_versions()
    assert _moved(base, after) == {"thresholds"}
    assert json.loads(after["thresholds"][1])["gate"]["max_ece"] == 0.05

    missing = vdirs["config"] / "benchmarks.yaml"
    missing.unlink()
    assert "benchmarks" not in versioning.current_versions()  # no file, no version (and no crash)


def test_prompt_hash_covers_common_text_and_role_file(vdirs):
    from lau import versioning

    base = versioning.current_versions()
    role_file = vdirs["prompts"] / "curator.md"
    role_file.write_text(role_file.read_text() + "\nAn extra rule.\n")
    one = versioning.current_versions()
    assert _moved(base, one) == {"prompt:curator"}

    common = vdirs["prompts"] / "_common.md"
    common.write_text(common.read_text() + "\nA shared rule.\n")
    two = versioning.current_versions()
    from lau.agents.runner import STANDALONE_ROLES

    cycle_prompts = {c for c in two if c.startswith("prompt:") and c.split(":", 1)[1] not in STANDALONE_ROLES}
    assert _moved(one, two) == cycle_prompts  # every cycle role changed; standalone prompts (ask) do not use it
    assert "_common" not in "".join(two)  # the shared file is part of each role, not a component of its own


def test_grants_hash_ignores_order_and_follows_content(vdirs, monkeypatch):
    from lau import versioning
    from lau.governance import grants

    base = versioning.current_versions()["grants"]
    monkeypatch.setattr(grants, "GRANTS", list(reversed(grants.GRANTS)))
    assert versioning.current_versions()["grants"] == base
    leaky = grants.Grant("ui", "SCHEMA", "holdout", privileges=("USE SCHEMA", "SELECT"))
    monkeypatch.setattr(grants, "GRANTS", [*grants.GRANTS, leaky])
    assert versioning.current_versions()["grants"][0] != base[0]


def test_code_version_clean_dirty_and_unknown(vdirs):
    from lau import versioning

    git, sha = vdirs["git"], "a" * 40
    assert versioning._code_version() == (sha[:12], json.dumps({"dirty": False, "git_sha": sha}, separators=(",", ":")))

    git["status"] = " M src/lau/cli.py\n?? src/lau/new.py\n"
    git["diff"] = "diff --git a/src/lau/cli.py b/src/lau/cli.py\n+change one\n"
    dirty, content = versioning._code_version()
    assert re.fullmatch(rf"{sha[:12]}-dirty-[0-9a-f]{{8}}", dirty)
    info = json.loads(content)
    assert info["dirty"] is True and info["git_sha"] == sha
    assert info["dirty_files"] == ["M src/lau/cli.py", "?? src/lau/new.py"]

    git["diff"] += "+change two\n"  # more uncommitted edits are a new version of the code
    assert versioning._code_version()[0] != dirty

    git["rev-parse"] = None  # git not available
    assert versioning._code_version()[0] == "unknown"


def test_real_git_lookup_yields_a_sha_or_unknown():
    from lau import versioning

    version_hash, content = versioning._code_version()
    assert re.fullmatch(r"unknown|[0-9a-f]{12}(-dirty-[0-9a-f]{8})?", version_hash)
    assert json.loads(content)["git_sha"] is None or len(json.loads(content)["git_sha"]) == 40


def test_record_writes_only_changed_components(lake, vdirs):
    from lau import versioning

    versioning.record_config_versions("align ledger with the private dirs")
    assert versioning.record_config_versions("nothing changed") == 0
    assert {r["state"] for r in versioning.compare()} == {"same"}

    _edit_yaml(vdirs["config"] / "budgets.yaml", lambda d: d["cycle"].update(max_experiments=7))
    (vdirs["prompts"] / "zz_test_role.md").write_text("A brand-new role.\n")  # never recorded before
    vdirs["git"]["rev-parse"] = "b" * 40 + "\n"
    assert versioning.record_config_versions("test change", recorded_by="tester") == 3

    st = _harness()
    rows = st.query(f"SELECT * FROM {st.fq('ops', 'config_versions')} WHERE reason = 'test change'")
    assert set(rows["component"]) == {"budgets", "prompt:zz_test_role", "code"}
    assert set(rows["recorded_by"]) == {"tester"}
    assert set(rows["git_sha"]) == {"b" * 40}  # every row carries the sha
    assert rows["recorded_at"].nunique() == 1
    budgets = rows[rows["component"] == "budgets"].iloc[0]
    assert json.loads(budgets["content_json"])["cycle"]["max_experiments"] == 7
    assert budgets["version_hash"] == versioning.current_versions()["budgets"][0]

    assert versioning.record_config_versions("again") == 0
    _edit_yaml(vdirs["config"] / "budgets.yaml", lambda d: d["cycle"].update(max_experiments=20))
    assert versioning.record_config_versions("reverted") == 1  # changing back is a change too


def test_record_defaults_recorded_by_to_the_os_user(lake, vdirs):
    from lau import versioning

    versioning.record_config_versions("align ledger with the private dirs")
    (vdirs["prompts"] / "zz_other_role.md").write_text("Another new role.\n")
    assert versioning.record_config_versions("default user") == 1
    st = _harness()
    who = st.query(f"SELECT recorded_by FROM {st.fq('ops', 'config_versions')} WHERE reason = 'default user'")
    assert who["recorded_by"].tolist() == [getpass.getuser()]


def test_try_record_never_raises(monkeypatch):
    from lau import versioning

    def boom():
        raise RuntimeError("store down")

    monkeypatch.setattr(versioning, "current_versions", boom)
    msgs: list[str] = []
    assert versioning.try_record_config_versions("x", log=msgs.append) == 0
    assert len(msgs) == 1 and "could not record config versions" in msgs[0] and "store down" in msgs[0]


def test_apply_records_versions_and_survives_a_broken_ledger(lake, vdirs, cfg_dir, definition_yaml, monkeypatch):
    from lau import versioning
    from lau.pipeline import definition_ops as ops

    versioning.record_config_versions("baseline for the apply test")
    _edit_yaml(vdirs["config"] / "thresholds.yaml", lambda d: d["gate"].update(max_ece=0.04))
    logs: list[str] = []
    try:
        res = ops.apply(
            definition_yaml({"delinquency_threshold_dpd": 120}),
            confirm=lambda q: True,
            run_cycle=False,
            log=logs.append,
        )
        st = _harness()
        rows = st.query(
            f"SELECT component, recorded_by FROM {st.fq('ops', 'config_versions')} "
            f"WHERE reason = 'definition apply {res['version']}'"
        )
        assert rows["component"].tolist() == ["thresholds"]
        assert rows["recorded_by"].tolist() == [getpass.getuser()]
    finally:
        # Put the 90 DPD definition back for the other tests, with the ledger itself broken: apply must still work.
        def boom():
            raise RuntimeError("ledger down")

        monkeypatch.setattr(versioning, "current_versions", boom)
        back = ops.apply(cfg_dir / "default_definition.yaml", confirm=lambda q: True, run_cycle=False, log=logs.append)
    assert back["version"] == lake["version"]
    assert any("could not record config versions" in m for m in logs)


# ---- live cycle visibility and stop control ---------------------------------------------------------------
class _Cycle:
    """`run_cycle` on the local lake with the agent runner replaced by a fake (no model calls)."""

    def __init__(self, orch) -> None:
        self.orch = orch
        self.calls: list[dict] = []  # one entry per agent run, in order
        self.hooks: dict = {}  # role -> callable(ctx) run inside that agent's "session"
        self.timeouts: set[str] = set()  # roles whose run ends is_error (like a wall-clock timeout)
        self.logs: list[str] = []

    def run(self) -> dict:
        self.logs = []
        return asyncio.run(self.orch.run_cycle("unit test", log=self.logs.append))


@pytest.fixture
def cycle(lake, monkeypatch):
    from lau.agents import orchestrator as orch
    from lau.agents.runner import AgentRunResult
    from lau.definition.registry import active_version

    version = active_version(_harness())
    monkeypatch.setattr(orch, "preflight", lambda: version)
    c = _Cycle(orch)

    async def fake_run_agent(role, prompt, tools, ctx):
        visible = len(_for_cycle("agent_trace", ctx.cycle_id)) if _harness().table_exists("ops", "agent_trace") else 0
        c.calls.append({"role": role, "trace_rows_visible": visible})
        ctx.trace.log(role, "fake_action", {"prompt": prompt[:20]}, {"ok": True})
        if role in c.hooks:
            c.hooks[role](ctx)
        ctx.spent_usd += 0.25
        if role == "modeling":
            ctx.experiments_used += 2
        timed_out = role in c.timeouts
        return AgentRunResult(
            role=role,
            text="done",
            cost_usd=0.25,
            num_turns=2,
            is_error=timed_out,
            subtype="timeout" if timed_out else "success",
            tool_calls=["t1"],
            duration_s=0.01,
        )

    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    return c


ROLES_RUN = ["planner", "profiler", "feature", "modeling", "curator"]  # no challenger -> no red team / compliance


def test_cycle_writes_heartbeats_and_flushes_the_trace_after_every_agent(lake, cycle):
    outcome = cycle.run()
    assert outcome["status"] == "completed"
    assert [c["role"] for c in cycle.calls] == ROLES_RUN

    hb = _for_cycle("cycle_heartbeat", outcome["cycle_id"])
    expected = [("start", "running")]
    expected += [(r, s) for r in ROLES_RUN for s in ("running", "done")] + [("end", "completed")]
    assert list(zip(hb["step"], hb["state"], strict=True)) == expected
    assert pd.isna(hb["agent"].iloc[0]) and pd.isna(hb["agent"].iloc[-1])  # cycle-level rows name no agent
    assert hb["agent"].iloc[1:-1].tolist() == [r for r in ROLES_RUN for _ in range(2)]
    assert hb["spent_usd"].is_monotonic_increasing and hb["experiments_used"].is_monotonic_increasing
    end = hb.iloc[-1]
    assert end["spent_usd"] == pytest.approx(0.25 * len(ROLES_RUN)) and end["experiments_used"] == 2
    modeling_running = hb[(hb["step"] == "modeling") & (hb["state"] == "running")].iloc[0]
    assert modeling_running["spent_usd"] == pytest.approx(0.75) and modeling_running["experiments_used"] == 0

    # each agent saw every earlier agent's trace rows already in ops.agent_trace (flushed per run, not at the end)
    assert [c["trace_rows_visible"] for c in cycle.calls] == list(range(len(ROLES_RUN)))
    assert len(_for_cycle("agent_trace", outcome["cycle_id"])) == len(ROLES_RUN)

    assert _cycle_row(outcome["cycle_id"])["status"].tolist() == ["completed"]


def test_cycle_records_changed_config_versions_before_it_starts(lake, cycle, vdirs):
    from lau import versioning

    versioning.record_config_versions("align ledger with the private dirs")
    _edit_yaml(vdirs["config"] / "budgets.yaml", lambda d: d["cycle"].update(max_experiments=9))
    outcome = cycle.run()
    cid = outcome["cycle_id"]

    st = _harness()
    rows = st.query(
        f"SELECT component, recorded_at FROM {st.fq('ops', 'config_versions')} WHERE reason = 'cycle {cid}'"
    )
    assert rows["component"].tolist() == ["budgets"]  # only what changed since the last record, tied to this cycle
    # recorded before the cycle's own start time, so "the ledger as of started_at" includes it
    assert rows["recorded_at"].iloc[0] <= _cycle_row(cid)["started_at"].iloc[0]
    assert versioning.recorded_versions()["budgets"]["version_hash"] == versioning.current_versions()["budgets"][0]


def test_stop_request_ends_the_cycle_gracefully(lake, cycle):
    from lau.agents.orchestrator import request_stop

    cycle.hooks["planner"] = lambda ctx: request_stop(ctx.cycle_id, "halt for test", "alice")
    outcome = cycle.run()
    cid = outcome["cycle_id"]

    assert outcome["status"] == "stopped_by_user" and outcome["stop_reason"] == "halt for test"
    assert [c["role"] for c in cycle.calls] == ["planner"]  # nothing started after the request
    ctl = _for_cycle("cycle_control", cid)
    assert list(zip(ctl["status"], ctl["requested_by"], ctl["reason"], ctl["action"], strict=True)) == [
        ("requested", "alice", "halt for test", "stop"),
        ("honored", "alice", "halt for test", "stop"),
    ]
    hb = _for_cycle("cycle_heartbeat", cid)
    assert list(zip(hb["step"], hb["state"], strict=True)) == [
        ("start", "running"),
        ("planner", "running"),
        ("planner", "done"),
        ("end", "stopped_by_user"),
    ]
    cyc = _cycle_row(cid)
    assert cyc["status"].tolist() == ["stopped_by_user"]
    assert json.loads(cyc["summary_json"].iloc[0])["stop_reason"] == "halt for test"
    assert "stopped_by_user" in Path(outcome["report"]).read_text()  # the cycle report is still written
    assert len(_for_cycle("agent_trace", cid)) == 1  # the run that did happen is in the audit trail
    assert any("stopped by alice" in m for m in cycle.logs)


def test_stop_without_a_reason_names_the_requester(lake, cycle):
    from lau.agents.orchestrator import request_stop

    cycle.hooks["profiler"] = lambda ctx: request_stop(ctx.cycle_id, "", "bob")
    outcome = cycle.run()
    assert outcome["status"] == "stopped_by_user" and outcome["stop_reason"] == "stop requested by bob"
    assert [c["role"] for c in cycle.calls] == ["planner", "profiler"]


def test_pending_stop_picks_the_earliest_request_for_this_cycle_only(lake):
    from lau.agents import orchestrator as orch
    from lau.agents.runner import CycleContext
    from lau.trace import TraceWriter

    def ctx_for(cid):
        return CycleContext(cid, "v", TraceWriter(cid, "v"))

    assert orch._pending_stop(ctx_for("cy-unit-none")) is None
    orch.request_stop("cy-unit-other", "not this cycle", "carol")
    orch.request_stop("cy-unit-pending", "first reason", "alice")
    orch.request_stop("cy-unit-pending", "second reason", "bob")
    stop = orch._pending_stop(ctx_for("cy-unit-pending"))
    assert (stop.requested_by, stop.reason) == ("alice", "first reason")
    assert orch._pending_stop(ctx_for("cy-unit-none")) is None


def test_a_timed_out_agent_is_an_error_beat_but_the_cycle_goes_on(lake, cycle):
    cycle.timeouts.add("profiler")
    outcome = cycle.run()
    assert outcome["status"] == "completed" and [c["role"] for c in cycle.calls] == ROLES_RUN
    hb = _for_cycle("cycle_heartbeat", outcome["cycle_id"])
    profiler = hb[hb["step"] == "profiler"]
    assert profiler["state"].tolist() == ["running", "error"]


def test_agent_api_error_is_an_error_beat_then_the_end_beat(lake, cycle):
    from lau.agents.runner import AgentRunError

    def api_down(ctx):
        raise AgentRunError("profiler: API Error 529")

    cycle.hooks["profiler"] = api_down
    outcome = cycle.run()
    assert outcome["status"] == "failed_agent_api"
    hb = _for_cycle("cycle_heartbeat", outcome["cycle_id"])
    assert list(zip(hb["step"], hb["state"], strict=True))[-3:] == [
        ("profiler", "running"),
        ("profiler", "error"),
        ("end", "failed_agent_api"),
    ]
    assert len(_for_cycle("agent_trace", outcome["cycle_id"])) == 2  # planner + the failing profiler run


def test_an_interrupted_cycle_is_never_recorded_as_completed(lake, cycle):
    def cancelled(ctx):
        raise asyncio.CancelledError

    cycle.hooks["feature"] = cancelled
    with pytest.raises(asyncio.CancelledError):
        cycle.run()
    cid = next(m.split()[1] for m in cycle.logs if m.startswith("cycle cy-"))
    cyc = _cycle_row(cid)
    assert cyc["status"].tolist() == ["failed"]
    assert "interrupted" in json.loads(cyc["summary_json"].iloc[0])["stop_reason"]
    hb = _for_cycle("cycle_heartbeat", cid)
    assert list(zip(hb["step"], hb["state"], strict=True))[-2:] == [("feature", "error"), ("end", "failed")]


def test_heartbeat_and_ledger_failures_never_break_a_cycle(lake, cycle, monkeypatch):
    from lau import versioning
    from lau.store import LocalStore

    real_write = LocalStore.write_df

    def flaky_write(self, key, table, df, mode="overwrite", partition=None):
        if table == "cycle_heartbeat":
            raise RuntimeError("warehouse hiccup")
        return real_write(self, key, table, df, mode, partition)

    def ledger_down():
        raise RuntimeError("ledger down")

    monkeypatch.setattr(LocalStore, "write_df", flaky_write)
    monkeypatch.setattr(versioning, "current_versions", ledger_down)
    outcome = cycle.run()
    assert outcome["status"] == "completed" and [c["role"] for c in cycle.calls] == ROLES_RUN
    assert any("heartbeat write failed" in m for m in cycle.logs)
    assert any("could not record config versions" in m for m in cycle.logs)


def test_trace_flush_keeps_rows_when_the_write_fails(lake, monkeypatch):
    from lau.store import LocalStore
    from lau.trace import TraceWriter

    tw = TraceWriter("cy-unit-trace", "v")
    tw.log("planner", "a")
    tw.log("planner", "b")
    real_write, failing = LocalStore.write_df, {"on": True}

    def flaky_write(self, key, table, df, mode="overwrite", partition=None):
        if table == "agent_trace" and failing["on"]:
            raise RuntimeError("transient")
        return real_write(self, key, table, df, mode, partition)

    monkeypatch.setattr(LocalStore, "write_df", flaky_write)
    with pytest.raises(RuntimeError):
        tw.flush()
    assert [r["action"] for r in tw.rows] == ["a", "b"]  # still buffered, in order
    tw.log("planner", "c")
    failing["on"] = False
    assert tw.flush() == 3 and tw.rows == []
    assert sorted(_for_cycle("agent_trace", "cy-unit-trace", "action")["action"]) == ["a", "b", "c"]


# ---- access checks ----------------------------------------------------------------------------------------
@pytest.fixture
def probe_tables(lake):
    """Tables the allow-probes read. A stand-in is enough (a probe tests permission, not contents) and is dropped
    again afterwards so the shared lake keeps the schemas the real writers create."""
    st, created = _harness(), []
    for key, table in (("ops", "cycles"), ("experiments", "reports")):
        if not st.table_exists(key, table):
            st.write_df(key, table, pd.DataFrame({"probe": ["x"]}), mode="overwrite")
            created.append((key, table))
    yield
    for key, table in created:
        st.drop_table(key, table)


def test_local_access_checks_match_the_grants_spec(lake, probe_tables):
    from lau.governance.access_checks import PROBES, run_access_checks

    rows = run_access_checks(write=True)
    assert len(rows) == sum(len(v["deny"]) + len(v["allow"]) for v in PROBES.values()) == 19
    assert all(r["ok"] for r in rows), [r for r in rows if not r["ok"]]
    got = {(r["role"], r["object"]): (r["expected"], r["observed"]) for r in rows}
    agent_deny = ["holdout.oot_labels", "labels.labels_all", "raw.protected_attributes", "raw.performance"]
    agent_deny += ["curated.applications", "ops.pipeline_state"]
    ui_deny = ["raw.performance", "holdout.oot_labels", "labels.labels_all", "curated.applications"]
    ui_deny += ["curated.cashflow_monthly"]
    for obj in agent_deny:
        assert got[("agent", obj)] == ("deny", "deny"), obj
    for obj in ["labels.labels_active", "curated.applications_dev", "curated.data_catalog"]:
        assert got[("agent", obj)] == ("allow", "allow"), obj
    for obj in ui_deny:
        assert got[("ui", obj)] == ("deny", "deny"), obj
    for obj in ["ops.cycles", "curated.data_catalog", "labels.split_meta", "experiments.reports"]:
        assert got[("ui", obj)] == ("allow", "allow"), obj
    assert got[("promoter", "holdout.oot_labels")] == ("deny", "deny")

    st = _harness()
    table = st.fq("ops", "access_checks")
    last = st.query(f"SELECT * FROM {table} WHERE checked_at = (SELECT max(checked_at) FROM {table})")
    assert list(last.columns) == ["checked_at", "role", "object", "expected", "observed", "ok", "detail"]
    assert len(last) == 19 and set(last["role"]) == {"agent", "ui", "promoter"} and bool(last["ok"].all())


def test_access_checks_only_write_when_asked(lake, probe_tables):
    from lau.governance.access_checks import run_access_checks

    before = _count("access_checks")
    assert len(run_access_checks(write=False)) == 19
    assert _count("access_checks") == before
    run_access_checks(write=True)
    assert _count("access_checks") == before + 19


def test_access_checks_flag_grants_that_break_isolation_or_usefulness(lake, probe_tables, monkeypatch):
    from lau.governance import grants
    from lau.governance.access_checks import run_access_checks

    def failing(rows):
        return [(r["role"], r["object"], r["expected"], r["observed"]) for r in rows if not r["ok"]]

    original = list(grants.GRANTS)
    leaky = grants.Grant("ui", "SCHEMA", "holdout", privileges=("USE SCHEMA", "SELECT"))
    monkeypatch.setattr(grants, "GRANTS", [*original, leaky])
    assert failing(run_access_checks(write=False)) == [("ui", "holdout.oot_labels", "deny", "allow")]

    starved = [g for g in original if not (g.role == "ui" and g.obj == "split_meta")]
    monkeypatch.setattr(grants, "GRANTS", starved)
    assert failing(run_access_checks(write=False)) == [("ui", "labels.split_meta", "allow", "deny")]


def test_an_unprovable_probe_is_an_error_not_a_pass(lake):
    from lau.governance.access_checks import _probe
    from lau.store import get_store

    row = _probe(get_store("ui"), "ui", "ops.no_such_table", "allow", datetime.now(UTC))
    assert row["observed"] == "error" and row["ok"] is False and row["detail"]
    row = _probe(get_store("ui"), "ui", "ops.no_such_table", "deny", datetime.now(UTC))
    assert row["observed"] == "error" and row["ok"] is False  # "could not tell" never counts as a denial


class _FakeUnityCatalog:
    """A Databricks-style store: only `_query` (Unity Catalog) may decide; the in-process ACL must stay out of it."""

    backend = "databricks"

    def __init__(self) -> None:
        self.closed = False

    def fq(self, schema, table):
        return f"cat.{schema}.{table}"

    def _query(self, sql):
        if "oot_labels" in sql:
            raise RuntimeError(
                "[INSUFFICIENT_PERMISSIONS] Insufficient privileges: User does not have SELECT on Table "
                "'cat.holdout.oot_labels'. SQLSTATE: 42501"
            )
        if "no_such_table" in sql:
            raise RuntimeError("[TABLE_OR_VIEW_NOT_FOUND] The table or view cannot be found")
        return pd.DataFrame({"a": [1]})

    def query(self, sql):
        raise AssertionError("on Databricks the in-process ACL must not decide")

    def close(self):
        self.closed = True


def test_databricks_probes_go_through_query_and_recognise_uc_denials():
    from lau.governance.access_checks import _is_denied, _probe

    st, now = _FakeUnityCatalog(), datetime.now(UTC)
    denied = _probe(st, "agent", "holdout.oot_labels", "deny", now)
    assert (denied["observed"], denied["ok"]) == ("deny", True) and "INSUFFICIENT_PERMISSIONS" in denied["detail"]
    allowed = _probe(st, "agent", "curated.data_catalog", "allow", now)
    assert (allowed["observed"], allowed["ok"]) == ("allow", True)
    wrong = _probe(st, "agent", "holdout.oot_labels", "allow", now)
    assert (wrong["observed"], wrong["ok"]) == ("deny", False)
    missing = _probe(st, "agent", "ops.no_such_table", "deny", now)
    assert (missing["observed"], missing["ok"]) == ("error", False)
    assert _is_denied(Exception("PERMISSION_DENIED: nope")) and not _is_denied(Exception("TABLE_OR_VIEW_NOT_FOUND"))


def test_roles_without_credentials_are_skipped_and_stores_are_closed(lake, monkeypatch):
    from lau.governance import access_checks

    stores = {"agent": _FakeUnityCatalog(), "promoter": _FakeUnityCatalog()}  # no ui credentials
    monkeypatch.setattr(access_checks, "_store_for", lambda role, s: stores.get(role))
    rows = access_checks.run_access_checks(write=False)
    assert {r["role"] for r in rows} == {"agent", "promoter"}
    assert all(st.closed for st in stores.values())


# ---- CLI --------------------------------------------------------------------------------------------------
@pytest.fixture
def cli(monkeypatch):
    from rich.console import Console
    from typer.testing import CliRunner

    from lau.cli import app

    # never let the identity table reach for real Databricks credentials that may be exported in the shell
    monkeypatch.setattr("lau.credentials.has_role_credentials", lambda role: False)
    # the CLI's console fixes its width at import time; use a wide, colourless one so tables never wrap
    monkeypatch.setattr("lau.cli.console", Console(width=200, force_terminal=False, color_system=None))
    runner = CliRunner()
    return lambda *args: runner.invoke(app, list(args))


def test_cli_versions_show_and_record(lake, vdirs, cli):
    first = cli("versions", "record", "--reason", "cli test")
    assert first.exit_code == 0, first.output
    shown = cli("versions", "show")
    assert shown.exit_code == 0, shown.output
    for component in ("thresholds", "protected_classes", "grants", "prompt:planner", "code"):
        assert component in shown.output
    assert "0 component(s) differ" in shown.output

    _edit_yaml(vdirs["config"] / "models.yaml", lambda d: d["agents"].update(curator="claude-haiku-4-5"))
    shown = cli("versions", "show")
    assert "changed" in shown.output and "1 component(s) differ" in shown.output
    recorded = cli("versions", "record", "--reason", "cli test 2")
    assert recorded.exit_code == 0 and "recorded 1 component(s): models" in recorded.output
    assert "nothing changed" in cli("versions", "record").output


def test_cli_stop_cycle_writes_a_request_for_a_running_cycle(lake, cli):
    st = _harness()
    now = datetime.now(UTC)

    def cycle_row(cid, status):
        return pd.DataFrame(
            [
                {
                    "cycle_id": cid,
                    "definition_version": "v",
                    "reason": "unit test",
                    "started_at": now,
                    "status": status,
                    "summary_json": "{}",
                }
            ]
        )

    try:
        st.write_df("ops", "cycles", cycle_row("cy-cli-running", "running"), mode="append")
        st.write_df("ops", "cycles", cycle_row("cy-cli-done", "completed"), mode="append")

        ok = cli("stop-cycle", "cy-cli-running", "--reason", "from the cli")
        assert ok.exit_code == 0, ok.output
        ctl = _for_cycle("cycle_control", "cy-cli-running")
        assert len(ctl) == 1
        row = ctl.iloc[0]
        assert (row["action"], row["status"], row["reason"]) == ("stop", "requested", "from the cli")
        assert row["requested_by"] == getpass.getuser()

        unknown = cli("stop-cycle", "cy-cli-missing")
        assert unknown.exit_code == 1 and "unknown cycle" in unknown.output
        finished = cli("stop-cycle", "cy-cli-done")
        assert finished.exit_code == 1 and "not running" in finished.output
        assert _for_cycle("cycle_control", "cy-cli-done").empty
    finally:
        st.execute(f"DELETE FROM {st.fq('ops', 'cycles')} WHERE cycle_id LIKE 'cy-cli-%'")


def test_cli_check_access_records_and_fails_on_a_leak(lake, probe_tables, cli, monkeypatch):
    from lau.governance import grants

    before = _count("access_checks")
    ok = cli("check-access")
    assert ok.exit_code == 0, ok.output
    assert "all 19 access checks ok" in ok.output and _count("access_checks") == before + 19

    leaky = grants.Grant("agent", "SCHEMA", "holdout", privileges=("USE SCHEMA", "SELECT"))
    monkeypatch.setattr(grants, "GRANTS", [*grants.GRANTS, leaky])
    bad = cli("check-access")
    assert bad.exit_code == 1, bad.output
    assert "FAIL" in bad.output and "1 of 19 access checks failed" in bad.output
    assert _count("access_checks") == before + 38  # failures are recorded too


# ---- the ui identity --------------------------------------------------------------------------------------
def test_init_dry_run_shows_read_only_ui_grants(lake):
    from lau.governance.uc_layout import plan_init

    ui = [line for line in plan_init() if "<ui-sp-app-id>" in line]
    assert any("USE CATALOG" in line for line in ui) and any("SELECT ON SCHEMA" in line for line in ui)
    assert any("TABLE" in line and "data_catalog" in line for line in ui)
    assert not any(w in line for line in ui for w in ("MODIFY", "CREATE", "ALL PRIVILEGES", "WRITE VOLUME"))
    # the only volume it may touch is the console snapshot, and only to read it
    volumes = [line for line in ui if "VOLUME" in line]
    assert volumes and all("GRANT READ VOLUME ON VOLUME" in line and "`console`" in line for line in volumes)


class _FakeWorkspace:
    """Just enough of WorkspaceClient for `ensure_service_principals`: records what would be created or granted."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.permissions: list[tuple[str, list]] = []
        outer = self

        class ServicePrincipals:
            def list(self, filter=None):
                return []

            def create(self, display_name, active, entitlements):
                outer.created.append(display_name)
                return SimpleNamespace(id=f"id-{display_name}", application_id=f"app-{display_name}")

        class Secrets:
            def create(self, sp_id):
                return SimpleNamespace(secret="not-a-real-secret")

        class Warehouses:
            def update_permissions(self, warehouse_id, access_control_list):
                outer.permissions.append((warehouse_id, access_control_list))

        self.service_principals = ServicePrincipals()
        self.service_principal_secrets_proxy = Secrets()
        self.warehouses = Warehouses()


def test_ensure_service_principals_creates_the_ui_identity_like_the_others(lake, monkeypatch):
    from lau.governance import principals
    from lau.settings import WorkspaceState, get_settings

    written: dict[str, str] = {}
    monkeypatch.setattr(principals, "write_env_values", lambda updates: written.update(updates))
    monkeypatch.setattr("lau.credentials.has_role_credentials", lambda role: False)
    w, state = _FakeWorkspace(), WorkspaceState(warehouse_id="wh-1")
    principals.ensure_service_principals(w, get_settings(), state, lambda m: None)

    assert set(state.service_principals) == {"harness", "agent", "promoter", "ui"}
    assert "lau-ui" in w.created
    assert written["LAU_UI_CLIENT_ID"] == "app-lau-ui" and written["LAU_UI_CLIENT_SECRET"]
    ui_acl = [acl for _, acl in w.permissions if acl[0].service_principal_name == "app-lau-ui"]
    assert len(ui_acl) == 1 and ui_acl[0][0].permission_level.value == "CAN_USE"


def test_ui_gets_no_mlflow_experiment_permission(lake):
    from lau.governance import principals
    from lau.settings import WorkspaceState, get_settings

    def missing(path):
        raise RuntimeError("no such experiment")

    acls: list[list] = []
    w = SimpleNamespace(
        workspace=SimpleNamespace(mkdirs=lambda path: None),
        experiments=SimpleNamespace(
            get_by_name=missing,
            create_experiment=lambda path, tags=None: SimpleNamespace(experiment_id="exp-1"),
            update_permissions=lambda exp_id, access_control_list: acls.append(access_control_list),
        ),
    )
    roles = ("harness", "agent", "promoter", "ui")
    sps = {r: {"id": f"id-{r}", "application_id": f"app-{r}", "display_name": r} for r in roles}
    principals.ensure_experiment(w, get_settings(), WorkspaceState(service_principals=sps), lambda m: None)
    assert {a.service_principal_name for a in acls[0]} == {"app-harness", "app-agent", "app-promoter"}


def test_teardown_blanks_credentials_of_every_service_principal_role(lake):
    from lau.governance.uc_layout import sp_roles
    from lau.settings import WorkspaceState, get_settings

    s = get_settings()
    assert sp_roles(s) == ["harness", "agent", "promoter", "ui"]  # configured SP roles; admin is the human
    state = WorkspaceState(service_principals={"ui": {"id": "1"}, "legacy": {"id": "2"}})
    assert sp_roles(s, state) == ["harness", "agent", "promoter", "ui", "legacy"]


def test_liveness_writes_heartbeats_while_an_agent_runs(lake):
    """A long agent run keeps beating (and flushing its trace), so a silent death is visible in the console."""
    import asyncio

    from lau.agents import orchestrator as orch
    from lau.agents.runner import CycleContext
    from lau.store import get_store
    from lau.trace import TraceWriter

    cid = "cy-test-liveness"
    ctx = CycleContext(cid, lake["version"], TraceWriter(cid, lake["version"]))
    ctx.trace.log("modeling", "list_features", {}, {"n": 3}, state_changing=False)

    async def long_run() -> None:
        done = asyncio.Event()
        beat = asyncio.create_task(orch._liveness(ctx, "modeling", done, log=lambda m: None, every_s=0.05))
        await asyncio.sleep(0.4)
        done.set()
        await beat

    asyncio.run(long_run())
    st = get_store("admin")
    try:
        beats = st.query(f"SELECT state FROM {st.fq('ops', 'cycle_heartbeat')} WHERE cycle_id = '{cid}'")
        trace = st.query(f"SELECT action FROM {st.fq('ops', 'agent_trace')} WHERE cycle_id = '{cid}'")
        assert len(beats) >= 2 and set(beats["state"]) == {"running"}
        assert list(trace["action"]) == ["list_features"]  # flushed mid-run, exactly once
    finally:
        for table in ("cycle_heartbeat", "agent_trace"):
            st.execute(f"DELETE FROM {st.fq('ops', table)} WHERE cycle_id = '{cid}'")


def test_curator_reverifies_only_flagged_lessons(tmp_path, monkeypatch):
    from lau.agents import lessons as L

    monkeypatch.setenv("LAU_LESSONS_FILE", str(tmp_path / "LESSONS.md"))  # never the session's shared file

    v_old, v_new = "a" * 12, "b" * 12
    L.write_lessons(
        [
            L.Lesson(
                "L-aaa111", v_old, "definition-specific", f"unverified-under-{v_new[:8]}", "AUC on thin files is low."
            ),
            L.Lesson(
                "L-bbb222", v_old, "definition-specific", f"unverified-under-{v_new[:8]}", "Bureau score dominates."
            ),
            L.Lesson("L-ccc333", v_new, "definition-specific", "active", "Already verified."),
        ]
    )
    changed = L.set_statuses(
        [
            {"id": "L-aaa111", "status": "active", "reason": "thin-file AUC 0.66 again"},
            {"id": "L-bbb222", "status": "retired", "reason": "cash-flow features now lead"},
            {"id": "L-ccc333", "status": "retired", "reason": "should not change"},
            {"id": "L-aaa111", "status": "bogus", "reason": "ignored"},
        ],
        v_new,
    )
    got = {le.id: (le.status, le.definition_version) for le in L.read_lessons()}
    assert changed == ["L-aaa111", "L-bbb222"]
    assert got["L-aaa111"] == ("active", v_new)  # verified lessons move to the active definition
    assert got["L-bbb222"][0] == "retired" and got["L-ccc333"] == ("active", v_new)


def test_inside_a_job_the_run_as_role_keeps_native_credentials(monkeypatch):
    """Jobs run as the harness identity with native auth (no client id): MLflow calls must not touch the env."""
    import os

    from lau.credentials import role_env

    monkeypatch.setenv("LAU_RUNTIME_ROLE", "harness")
    monkeypatch.setenv("DATABRICKS_HOST", "https://runtime.example")
    monkeypatch.delenv("DATABRICKS_CLIENT_ID", raising=False)
    with role_env("harness"):
        assert os.environ["DATABRICKS_HOST"] == "https://runtime.example"
        assert "DATABRICKS_CLIENT_ID" not in os.environ
    assert os.environ["DATABRICKS_HOST"] == "https://runtime.example"


def test_approval_counts_never_invalidate_pipeline_stages(monkeypatch):
    """Governance-only config (who must approve) must not retrain the baseline or move the harness reference."""
    from lau.pipeline import stages

    s = stages.get_settings()
    before = stages.config_fingerprint(None)
    monkeypatch.setitem(s.thresholds, "approvals", {"promotion": {"dev": 5, "prod": 9}})
    assert stages.config_fingerprint(None) == before
    monkeypatch.setitem(s.thresholds, "gate", {**s.thresholds["gate"], "unit_probe": 1})
    assert stages.config_fingerprint(None) != before


def test_job_pins_match_the_locked_model_libraries():
    """Jobs load models pickled locally: the serverless environment must run the same model library versions."""
    from importlib.metadata import version

    jobs = (Path(__file__).resolve().parents[2] / "resources" / "jobs.yml").read_text()
    for lib in ("scikit-learn", "lightgbm", "xgboost"):
        pins = set(re.findall(rf'"{lib}==([^"]+)"', jobs))
        assert pins == {version(lib)}, f"{lib}: jobs.yml pins {pins or 'nothing'}, uv.lock has {version(lib)}"


def test_switching_roles_never_reuses_another_roles_mlflow_client(monkeypatch):
    """MLflow caches its Databricks client by host and profile only; each role switch must drop it, or the first
    identity in a process would make every later call (a promoter registering a model ran as the harness)."""
    import os
    from types import SimpleNamespace

    import mlflow.utils.rest_utils as rest

    from lau import credentials

    made: list[str] = []

    def fake_client(*args, **kwargs):
        made.append(os.environ.get("DATABRICKS_CLIENT_ID", ""))
        return made[-1]

    cached = rest.lru_cache(maxsize=5)(fake_client)
    monkeypatch.setattr(rest, "get_workspace_client", cached)
    roles = {"harness": "cid-harness", "promoter": "cid-promoter"}
    monkeypatch.setattr(
        credentials,
        "databricks_config",
        lambda role: SimpleNamespace(host="https://example", client_id=roles[role], client_secret="s", token=None),
    )
    monkeypatch.delenv("LAU_RUNTIME_ROLE", raising=False)
    for role in ("harness", "promoter", "harness"):
        with credentials.role_env(role):
            assert rest.get_workspace_client(False, "https://example", None, None) == roles[role]
    assert made == ["cid-harness", "cid-promoter", "cid-harness"]


def test_an_acknowledgement_carries_to_repeats_of_the_same_alert_until_it_worsens_or_expires(lake):
    """Monitoring re-raises a persistent condition every run: a person's acknowledgement covers the repeats for 30 days
    unless the value got materially worse, so the daily notify task does not page for a known condition."""
    from datetime import timedelta

    from lau.console.services import ops
    from lau.console.util import clear_cache
    from lau.store import get_store

    st = get_store("harness")
    t0 = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
    rows = [
        (t0, 0.31),  # acknowledged by a person
        (t0 + timedelta(days=1), 0.315),  # the same condition again: carried
        (t0 + timedelta(days=2), 0.40),  # materially worse (+0.09 PSI): needs a person
        (t0 + timedelta(days=40), 0.31),  # same value, but the acknowledgement expired
    ]
    alerts = pd.DataFrame(
        [
            {
                "kind": "psi",
                "subject": "unit_carry_feature",
                "value": v,
                "severity": "high",
                "ts": ts,
                "definition_version": "vcarry",
            }
            for ts, v in rows
        ]
    )
    st.write_df("ops", "alerts", alerts, mode="append")
    first = ops.alert_id(pd.Timestamp(t0), "psi", "unit_carry_feature")
    st.write_df(
        "ops",
        "alert_acks",
        pd.DataFrame(
            [{"alert_id": first, "acked_at": t0 + timedelta(hours=1), "acked_by": "alice", "note": "known drift"}]
        ),
        mode="append",
    )
    clear_cache()
    mine = sorted((a for a in ops.alerts() if a["subject"] == "unit_carry_feature"), key=lambda a: a["ts"])
    assert [(a["acknowledged"], a["ack_carried"]) for a in mine] == [
        (True, False),
        (True, True),
        (False, False),
        (False, False),
    ]
    assert mine[1]["ack_by"] == "alice"
