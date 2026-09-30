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
    """Read-only: verify each identity and the platform-level isolation (agent denied on holdout)."""
    from databricks.sdk import WorkspaceClient

    from lau.credentials import databricks_config, has_role_credentials
    from lau.settings import get_settings

    s = get_settings()
    t = Table("role", "identity", "status")
    for role in ("admin", "harness", "agent", "promoter"):
        if not has_role_credentials(role):
            t.add_row(role, "-", "no credentials in .env" + (" (run `lau init`)" if role != "admin" else ""))
            continue
        try:
            me = WorkspaceClient(config=databricks_config(role)).current_user.me()
            t.add_row(role, me.user_name or me.display_name or "?", "ok")
        except Exception as e:  # noqa: BLE001
            t.add_row(role, "-", f"error: {str(e)[:80]}")
    console.print(t)
    if s.project.backend == "databricks" and s.state.warehouse_id and has_role_credentials("agent"):
        from lau.store import DatabricksStore

        st = DatabricksStore("agent", s)
        try:
            st._query(f"SELECT * FROM {s.fq('holdout', 'oot_labels')} LIMIT 1")
            console.print("[red]✗ agent principal CAN read holdout — isolation broken[/red]")
        except Exception as e:  # noqa: BLE001
            ok = any(k in str(e) for k in ("PERMISSION_DENIED", "INSUFFICIENT_PERMISSIONS", "does not have"))
            console.print(
                "[green]✓[/green] agent denied on holdout by Unity Catalog"
                if ok
                else f"[yellow]? agent holdout query failed for another reason: {str(e)[:160]}[/yellow]"
            )
        st.close()


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


@app.command()
def teardown(yes: bool = typer.Option(False, "--yes")) -> None:
    """Remove everything this project created (catalog/schemas, SPs, warehouse, experiment)."""
    from lau.governance.uc_layout import run_teardown

    if not yes and not typer.confirm("Permanently remove all project resources?"):
        raise typer.Exit(0)
    _guard(run_teardown, _log, yes)


if __name__ == "__main__":
    app()
