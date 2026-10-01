"""`lau` CLI. Only a human at this CLI can change the default definition, approve, or promote."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
import warnings  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning, module="mlflow")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*can_use_tool will not be invoked.*")  # PreToolUse hook gates every call

import typer  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
dd = typer.Typer(no_args_is_help=True, help="Default-definition lifecycle (plan | apply | compare).")
app.add_typer(dd, name="default-definition")


def _mount_evidence() -> None:
    from lau.evidence.cli import app as evidence_app

    app.add_typer(evidence_app, name="evidence")


_mount_evidence()
versions = typer.Typer(
    no_args_is_help=True, help="Version ledger for config, prompts, grants and code (show | record)."
)
app.add_typer(versions, name="versions")
console = Console()


def _log(msg: str) -> None:
    console.print(msg, markup=False, highlight=False)


def _fail(msg: str) -> None:
    console.print(f"[red]✗ {msg}[/red]")
    raise typer.Exit(1)


def _guard(fn, *a, **kw):
    from lau.credentials import CredentialsMissingError

    try:
        return fn(*a, **kw)
    except CredentialsMissingError as e:
        _fail(str(e))


# ---------------------------------------------------------------------------------------------------------
@app.command("check-access")
def check_access() -> None:
    """Verify each identity, then probe isolation as agent, ui and promoter; results go to ops.access_checks.

    Exits 1 if any probe is not as expected (a read that should be denied, a denial that should be a read, or a
    probe that could not tell).
    """
    from databricks.sdk import WorkspaceClient
    from rich.markup import escape

    from lau.credentials import databricks_config, has_role_credentials
    from lau.governance.access_checks import record_access_checks, run_access_checks

    t = Table("role", "identity", "status")
    for role in ("admin", "harness", "agent", "promoter", "ui"):
        if not has_role_credentials(role):
            t.add_row(role, "-", "no credentials in .env" + (" (run `lau init`)" if role != "admin" else ""))
            continue
        try:
            me = WorkspaceClient(config=databricks_config(role)).current_user.me()
            t.add_row(role, me.user_name or me.display_name or "?", "ok")
        except Exception as e:  # noqa: BLE001
            t.add_row(role, "-", f"error: {str(e)[:80]}")
    console.print(t)
    rows = _guard(run_access_checks, False)
    if not rows:
        _log("no access probes ran (workspace not initialised, or no role credentials in .env)")
        return
    pt = Table("role", "object", "expected", "observed", "result")
    for r in rows:
        result = "[green]ok[/green]" if r["ok"] else f"[red]FAIL[/red] {escape(r['detail'][:70])}"
        pt.add_row(r["role"], r["object"], r["expected"], r["observed"], result)
    console.print(pt)
    try:
        record_access_checks(rows)
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]? results not recorded in ops.access_checks: {escape(str(e)[:160])}[/yellow]")
    failed = [r for r in rows if not r["ok"]]
    if failed:
        console.print(f"[red]✗ {len(failed)} of {len(rows)} access checks failed[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] all {len(rows)} access checks ok ({', '.join(sorted({r['role'] for r in rows}))})")


@app.command()
def init(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be created; create nothing."),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt."),
) -> None:
    """Create catalog/schemas/volumes, 2X-Small warehouse, service principals, grants, MLflow experiment."""
    from lau.governance.uc_layout import plan_init, run_init

    for line in plan_init():
        _log(line)
    if dry_run:
        return
    if not yes and not typer.confirm("Create these resources?"):
        raise typer.Exit(0)
    state = _guard(run_init, _log)
    _log(
        f"done: catalog={state.catalog} prefix='{state.schema_prefix}' warehouse={state.warehouse_id} "
        f"SPs={list(state.service_principals)}"
    )


@app.command("gen-data")
def gen_data(
    n: int = typer.Option(None, help="applications (default from config/synth.yaml)"), seed: int = typer.Option(None)
) -> None:
    """Generate synthetic raw data (applications + monthly performance), write raw tables."""
    from lau.synth.ingest import gen_data as _gen

    _guard(_gen, n, seed, _log)


# ---------------------------------------------------------------------------------------------------------
@dd.command("plan")
def dd_plan(
    approve: bool = typer.Option(False, "--approve", help="Record approval of this exact hash (for CI)."),
) -> None:
    """Diff vs active, affected stages, estimated cost and label-rate impact."""
    from lau.definition import registry
    from lau.pipeline import definition_ops as ops
    from lau.store import get_store

    p = _guard(ops.plan, log=_log)
    _log(p.render())
    if approve and not p.is_noop:
        if not sys.stdin.isatty():
            _fail("--approve requires an interactive terminal (a human)")
        if typer.confirm(f"Record approval for definition {p.version}?"):
            aid = registry.record_approval(get_store("harness"), p.version, p.render())
            _log(f"approval recorded: {aid}")


@dd.command("apply")
def dd_apply(
    yes: bool = typer.Option(False, "--yes", help="Confirm non-interactively (you are the approver)."),
    approval_id: str = typer.Option(None, help="Use a recorded approval (CI/job path)."),
    no_cycle: bool = typer.Option(False, "--no-cycle", help="Do not start an improvement cycle."),
) -> None:
    """Apply config/default_definition.yaml: activate, invalidate and rebuild everything downstream."""
    from lau.pipeline import definition_ops as ops

    if approval_id:
        confirm = None
    elif yes:
        confirm = lambda q: True  # noqa: E731 - explicit human flag
    elif sys.stdin.isatty():
        confirm = typer.confirm
    else:
        confirm = None  # non-interactive without --yes: requires a recorded approval
    from lau.credentials import has_anthropic_key

    run_cycle = not no_cycle and has_anthropic_key()
    res = _guard(ops.apply, confirm=confirm, approval_id=approval_id, run_cycle=run_cycle, log=_log)
    _log(json.dumps({k: v for k, v in res.items() if k != "details"}, indent=1, default=str))


@dd.command("compare")
def dd_compare(other: Path = typer.Argument(..., help="YAML of the other definition")) -> None:
    """Build another definition side by side (not activated) and compare label rates, performance, importance."""
    from lau.pipeline import definition_ops as ops

    out = _guard(ops.compare, other, log=_log)
    _log(out.read_text())
    _log(f"report: {out}")


# ---------------------------------------------------------------------------------------------------------
@versions.command("show")
def versions_show() -> None:
    """Current hash of every versioned component vs the latest one recorded in ops.config_versions."""
    from lau import versioning

    rows = _guard(versioning.compare)
    t = Table("component", "current", "recorded", "state", "recorded at (UTC)")
    color = {"same": "green", "changed": "yellow", "new": "yellow"}
    for r in rows:
        at = "-" if r["recorded_at"] is None else str(r["recorded_at"])[:19]
        t.add_row(r["component"], r["current"], r["recorded"] or "-", f"[{color[r['state']]}]{r['state']}[/]", at)
    console.print(t)
    pending = [r["component"] for r in rows if r["state"] != "same"]
    _log(
        f"{len(pending)} component(s) differ from the last recorded version"
        + ("; `lau versions record` appends them." if pending else ".")
    )


@versions.command("record")
def versions_record(reason: str = typer.Option("manual", "--reason", help="why this snapshot is taken")) -> None:
    """Append a row for every component whose hash changed since it was last recorded."""
    import getpass

    from lau import versioning

    pending = [r["component"] for r in _guard(versioning.compare) if r["state"] != "same"]
    n = _guard(versioning.record_config_versions, reason, getpass.getuser())
    _log(f"recorded {n} component(s): {', '.join(pending)}" if n else "nothing changed since the last record")


# ---------------------------------------------------------------------------------------------------------
@app.command()
def profile() -> None:
    """Run only the data-profiler agent against the active definition."""
    import asyncio

    from lau.agents.orchestrator import run_single_agent

    res = _guard(lambda: asyncio.run(run_single_agent("profiler")))
    _log(json.dumps(res, indent=1, default=str))


@app.command("run-cycle")
def run_cycle(reason: str = "manual") -> None:
    """Run one improvement cycle (agents propose; harness judges). Prints estimated and actual cost."""
    from lau.agents.orchestrator import run_cycle_sync

    res = _guard(run_cycle_sync, reason, _log)
    _log(json.dumps({k: v for k, v in res.items() if k not in ("steps",)}, indent=1, default=str)[:6000])


@app.command("stop-cycle")
def stop_cycle(
    cycle_id: str = typer.Argument(..., help="cycle to stop, e.g. cy-202609301450-2e0e (see `lau status`)"),
    reason: str = typer.Option("", "--reason", help="why; recorded with the request and shown in the console"),
    by: str = typer.Option("", "--by", help="who asked (default: the OS user)"),
    as_json: bool = typer.Option(False, "--json", help="print one JSON ActionResult line"),
) -> None:
    """Ask a running cycle to end gracefully before its next agent run (it finishes as stopped_by_user)."""
    import getpass

    from lau.console import actions
    from lau.store import get_store

    st = get_store("harness")
    cid = cycle_id.replace("'", "''")
    cyc = (
        st.query(f"SELECT status FROM {st.fq('ops', 'cycles')} WHERE cycle_id = '{cid}'")
        if st.table_exists("ops", "cycles")
        else None
    )
    if cyc is None or cyc.empty:
        result = {"ok": False, "message": f"unknown cycle {cycle_id}", "ref": cycle_id}
    elif str(cyc["status"].iloc[0]) != "running":
        result = {"ok": False, "message": f"cycle {cycle_id} is not running ({cyc['status'].iloc[0]})", "ref": cycle_id}
    else:
        result = _guard(actions.stop, cycle_id, reason, by or getpass.getuser())
    _action_done(result, as_json)


@app.command()
def evaluate(model_version: str, count: bool = typer.Option(False, help="count as a validation test")) -> None:
    """Harness evaluation of a registered candidate on validation (no holdout)."""
    from lau.definition.registry import active_version
    from lau.harness.evaluate import evaluate_model
    from lau.modeling import registry_io
    from lau.store import get_store

    v = active_version(get_store("harness"))
    m = registry_io.load_pd_model(registry_io.candidate_uri(model_version), "harness")
    ev = evaluate_model(m, v, f"candidate:{model_version}", count_test=count)
    _log(
        json.dumps(
            {
                k: ev[k]
                for k in ("validation", "reference", "required_margin", "n_tests", "checks", "passed_validation")
            },
            indent=1,
            default=str,
        )
    )


@app.command()
def promote(
    model_version: str, rationale: str = typer.Option(None, help="approval rationale (prompted if omitted)")
) -> None:
    """Gate (holdout) -> show results -> human approval -> promote as champion for its definition."""
    from lau.harness.gate import promotion_gate
    from lau.modeling import registry_io
    from lau.promotion import promote as P
    from lau.store import get_store

    ref = f"candidate:{model_version}"
    tags = registry_io.version_tags(registry_io.candidate_model_name(), model_version, "harness")
    version = tags["definition_version"]
    reports = P.required_reports(get_store("harness"), ref, version)
    verdicts = {k: (v or {}).get("verdict") for k, v in reports.items()}
    _log(f"review verdicts: {verdicts}")
    if any(v is None for v in reports.values()):
        _fail("red-team and compliance reports are required (run a cycle)")
    m = registry_io.load_pd_model(registry_io.candidate_uri(model_version), "harness")
    gate = promotion_gate(m, version, ref)
    _log(json.dumps(gate, indent=1, default=str))
    if not gate["passed"]:
        _fail("harness gate failed; nothing promoted")
    if not sys.stdin.isatty():
        _fail("approval requires an interactive human at the terminal")
    decision = (
        "approve"
        if typer.confirm(f"APPROVE candidate {model_version} as champion for definition {version}?")
        else "reject"
    )
    why = rationale or typer.prompt("Rationale")
    aid = P.record_approval(ref, decision, why, gate["gate_id"], version)
    _log(f"approval recorded: {aid} ({decision})")
    if decision == "approve":
        P.promote(model_version, log=_log)


def _action_done(result: dict, as_json: bool, publish: bool = True) -> None:
    """Print an ActionResult (one JSON line with --json), refresh the console snapshot, exit 1 on failure."""
    if publish and result.get("ok"):
        from lau.console.snapshot import publish_quietly

        publish_quietly("cli", log_fn=(lambda m: None) if as_json else _log)
    if as_json:
        print(json.dumps(result, default=str))
    else:
        (_log if result.get("ok") else console.print)(("" if result.get("ok") else "✗ ") + str(result.get("message")))
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("gate")
def gate_cmd(
    candidate_ref: str = typer.Argument(..., help="e.g. candidate:7"),
    as_json: bool = typer.Option(False, "--json", help="print one JSON ActionResult line"),
) -> None:
    """Run the holdout promotion gate for a validated candidate (uses one of the definition's holdout reads)."""
    from lau.console import actions

    _action_done(_guard(actions.run_gate, candidate_ref), as_json)


@app.command("decide")
def decide_cmd(
    candidate_ref: str = typer.Argument(..., help="e.g. candidate:7"),
    decision: str = typer.Option(..., "--decision", help="approve or reject"),
    rationale: str = typer.Option(..., "--rationale", help="why (at least 10 characters)"),
    approver: str = typer.Option("", "--approver", help="who decides (default: the OS user)"),
    as_json: bool = typer.Option(False, "--json", help="print one JSON ActionResult line"),
) -> None:
    """Record a person's decision on the candidate's latest passing gate result (two-person rule applies)."""
    import getpass

    from lau.console import actions

    _action_done(_guard(actions.decide, candidate_ref, decision, rationale, approver or getpass.getuser()), as_json)


@app.command("promote-approved")
def promote_approved_cmd(
    candidate_ref: str = typer.Argument(..., help="e.g. candidate:7"),
    as_json: bool = typer.Option(False, "--json", help="print one JSON ActionResult line"),
) -> None:
    """Promote a candidate whose latest passing gate has the required approvals (promoter identity)."""
    from lau.console import actions

    _action_done(_guard(actions.promote, candidate_ref), as_json)


@app.command("ack-alert")
def ack_alert_cmd(
    alert_id: str = typer.Argument(..., help="alert id as shown in the console"),
    note: str = typer.Option("", "--note"),
    by: str = typer.Option("", "--by", help="who acknowledges (default: the OS user)"),
    as_json: bool = typer.Option(False, "--json", help="print one JSON ActionResult line"),
) -> None:
    """Acknowledge a monitoring alert (it stays in the history)."""
    import getpass

    from lau.console import actions

    _action_done(_guard(actions.ack, alert_id, note, by or getpass.getuser()), as_json)


snapshot_app = typer.Typer(no_args_is_help=True, help="Console snapshot for a console running on your machine.")
app.add_typer(snapshot_app, name="console-snapshot")


@snapshot_app.command("publish")
def snapshot_publish() -> None:
    """Publish the tables the console may read to the console volume (reads as the ui identity)."""
    from lau.console.snapshot import publish

    _guard(publish, "cli", _log)


@app.command()
def shadow() -> None:
    """Shadow-score new applications with serving + challenger models (no decisions affected)."""
    from lau.promotion.shadow import run_shadow

    _guard(run_shadow, _log)


@app.command()
def monitor() -> None:
    """PSI/score drift and outcome monitoring; alerts may enqueue a new cycle."""
    from lau.promotion.monitor import run_monitor

    _guard(run_monitor, _log)


@app.command()
def status() -> None:
    """Active definition, serving model (and its definition), pipeline freshness, latest cycle, costs."""
    from lau import cost
    from lau.definition import registry
    from lau.modeling import registry_io
    from lau.pipeline import definition_ops as ops
    from lau.store import get_store

    st = get_store("harness")
    active = registry.active_version(st)
    if active is None:
        _log("No active definition. Run `lau default-definition plan` then `apply`.")
        return
    d = registry.get_definition(st, active)
    _log(
        f"Active definition: {active} ({d.metadata.name}): {d.delinquency_threshold_dpd} DPD "
        f"{d.delinquency_timing} / {d.observation_window_months}m"
    )
    serving = registry_io.serving_model("harness")
    if serving:
        sup = serving.get("definition_version") != active
        _log(
            f"Serving model: {registry_io.production_model_name()} v{serving['model_version']} trained under "
            f"definition {serving.get('definition_version')}"
            + ("  ⚠ SUPERSEDED — no champion approved yet for the active definition" if sup else "")
        )
    else:
        _log("Serving model: none promoted yet (legacy policy score in effect)")
    ch = registry_io.alias_version(registry_io.candidate_model_name(), registry_io.challenger_alias(active), "harness")
    _log(f"Challenger for active definition: {('v' + ch[0]) if ch else 'none'}")
    p = ops.plan(with_impact=False)
    if p.version != active:
        _log(f"⚠ default_definition.yaml ({p.version}) differs from active ({active}): run plan/apply")
    t = Table("stage", "freshness", "reason")
    for name, stt, why in p.stages:
        t.add_row(name, stt, why)
    console.print(t)
    if st.table_exists("ops", "cycles"):
        cyc = st.query(
            f"SELECT cycle_id, definition_version, status, started_at FROM {st.fq('ops', 'cycles')} "
            "ORDER BY started_at DESC LIMIT 3"
        )
        _log("Recent cycles:\n" + cyc.to_string(index=False))
    _log(
        f"Month-to-date cost logged: ${cost.month_to_date_usd():.2f} "
        f"(hard stop ${st.s.budgets['monthly']['hard_stop_usd']:.0f})"
    )


@app.command("cost")
def cost_cmd(days: int = 7) -> None:
    """Actual DBUs for the project warehouse from system.billing.usage (lags hours) + logged spend."""
    from lau import cost

    _log(cost.billing_actuals(days).to_string(index=False) or "(no billing rows yet)")
    _log(f"month-to-date logged: ${cost.month_to_date_usd():.2f}")


@app.command("console")
def console_cmd(
    port: int = typer.Option(8765, help="API port"),
    host: str = typer.Option("127.0.0.1", help="Bind address (keep on localhost for local use)"),
    actions: bool = typer.Option(False, "--actions", help="Enable human actions (gate, approve, promote, stop)"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (development)"),
    mirror: bool = typer.Option(
        False, "--mirror", help="Mirror the workspace through the console snapshot (no SQL warehouse while you browse)"
    ),
    mirror_dir: Path = typer.Option(Path(".local_lake/console_mirror"), help="Where the mirror keeps its local copy"),
) -> None:
    """Run the Underwriting Console (API + built web app) locally."""
    import uvicorn

    if actions:
        os.environ["LAU_CONSOLE_ACTIONS"] = "1"
    if mirror:
        os.environ.update(LAU_CONSOLE_MIRROR="1", LAU_BACKEND="local", LAU_LOCAL_LAKE=str(mirror_dir.resolve()))
    mode = "mirror of the workspace" if mirror else "direct"
    state = "ON" if actions else "off"
    _log(f"Underwriting Console on http://{host}:{port}  ({mode}; actions {state}; API docs /api/docs)")
    uvicorn.run("lau.console.app:app", host=host, port=port, reload=reload, log_level="warning")


@app.command()
def teardown(yes: bool = typer.Option(False, "--yes")) -> None:
    """Remove everything this project created (catalog/schemas, SPs, warehouse, experiment)."""
    from lau.governance.uc_layout import run_teardown

    if not yes and not typer.confirm("Permanently remove all project resources?"):
        raise typer.Exit(0)
    _guard(run_teardown, _log, yes)


if __name__ == "__main__":
    app()
