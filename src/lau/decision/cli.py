"""`lau policy`, `lau decision` and `lau rollout`: credit policy approval, the decision model and its rollouts.

Approving a policy needs a person at an interactive terminal. Rollout decisions record who decided; serving and
rollback run as the promoter identity. Nothing here creates compute except `lau decision deploy --create`.
"""

from __future__ import annotations

import getpass
import json
import sys

import typer

policy_app = typer.Typer(
    no_args_is_help=True, help="Credit policy: cut-offs, knock-outs, bands (plan | approve | apply)."
)
decision_app = typer.Typer(no_args_is_help=True, help="Decision model and endpoint, synthetic traffic, release checks.")
rollout_app = typer.Typer(no_args_is_help=True, help="Shadow-first rollouts of promoted champions.")
feed_app = typer.Typer(no_args_is_help=True, help="Loan status feed: simulated servicer, ingestion, maturation.")


def _cli():
    import lau.cli as cli

    return cli


def _print(obj) -> None:
    _cli()._log(json.dumps(obj, indent=1, default=str))


# ---- policy ----------------------------------------------------------------------------------------------------------
@policy_app.command("plan")
def policy_plan() -> None:
    """Show config/policy.yaml against the active policy, and its approvals."""
    from lau.decision import policy

    p = _cli()._guard(policy.plan)
    log = _cli()._log
    log(f"Policy in YAML : {p['version']} ({p['name']})")
    log(f"Active policy  : {p['active'] or '(none: no decision model can be built)'}")
    if p["is_noop"]:
        log("Unchanged.")
    for d in p["diff"]:
        log(f"  {d['field']}: {d['before']!r} -> {d['after']!r}")
    log(f"Approvals: {len(p['approvers'])} of {p['required']} ({', '.join(p['approvers']) or 'none yet'})")


@policy_app.command("approve")
def policy_approve(note: str = typer.Option(None, "--note", help="what you checked (prompted if omitted)")) -> None:
    """Approve the policy in config/policy.yaml (interactive: a person reads the change and confirms)."""
    from lau.decision import policy

    cli = _cli()
    p = cli._guard(policy.plan)
    if p["is_noop"]:
        cli._fail("this policy is already active")
    policy_plan()
    if not sys.stdin.isatty():
        cli._fail("approving a policy requires a person at an interactive terminal")
    who = getpass.getuser()
    if who in p["approvers"]:
        cli._fail(f"{who} already approved policy {p['version']}")
    if not typer.confirm(f"APPROVE policy {p['version']} as {who}?"):
        cli._fail("not approved")
    why = note or typer.prompt("Note (what you checked)")
    v = policy.record_approval(policy.load_policy(), who, why)
    cli._log(f"approval recorded for policy {v} by {who}")


@policy_app.command("apply")
def policy_apply() -> None:
    """Activate the approved policy, then rebuild the decision model (and update the endpoint if it exists)."""
    from lau.decision import build, policy

    cli = _cli()
    try:
        r = cli._guard(policy.apply)
    except policy.PolicyNotActiveError as e:
        cli._fail(str(e))
    if not r["changed"]:
        cli._log(f"policy {r['version']} is already active")
        return
    cli._log(f"policy {r['version']} is active (was {r.get('previous') or 'none'})")
    cli._guard(build.publish, cli._log)


# ---- decision model and endpoint -------------------------------------------------------------------------------------
@decision_app.command("status")
def decision_status() -> None:
    """What decides right now; whether registry, live build and endpoint agree."""
    from lau.decision import build

    _print(_cli()._guard(build.status))


@decision_app.command("build")
def decision_build() -> None:
    """Build and register the decision model from approved state (a no-op when nothing changed)."""
    from lau.decision import build, policy

    cli = _cli()
    try:
        cli._guard(build.build, cli._log)
    except policy.PolicyNotActiveError as e:
        cli._fail(str(e))


@decision_app.command("deploy")
def decision_deploy(
    create: bool = typer.Option(False, "--create", help="create the endpoint if missing (compute: needs approval)"),
    version: str = typer.Option(None, "--version", help="decision model version (default: live)"),
) -> None:
    """Point the Model Serving endpoint at the live decision model."""
    from lau.decision import build

    cli = _cli()
    _print(cli._guard(build.deploy, version, create, cli._log))


@decision_app.command("originate")
def decision_originate(
    months: int = typer.Option(None, "--months", help="simulated months to send (default: config)"),
    via: str = typer.Option("auto", "--via", help="auto | endpoint | inprocess"),
) -> None:
    """Send the next simulated month(s) of synthetic applications for decisions."""
    from lau.decision import traffic

    cli = _cli()
    try:
        cli._guard(traffic.originate, months, via, cli._log)
    except traffic.NoDecisionModelError as e:
        cli._fail(str(e))


@decision_app.command("check")
def decision_check(
    which: str = typer.Argument(..., help="parity | load | rollback"),
    n: int = typer.Option(None, "--n", help="applications (default 200 parity, 300 load, 100 rollback)"),
    via: str = typer.Option("auto", "--via", help="load test transport: auto | endpoint | inprocess"),
    concurrency: int = typer.Option(4, "--concurrency"),
) -> None:
    """Release checks: training-serving parity, latency under load, rollback drill."""
    from lau.decision import checks

    cli = _cli()
    if which == "parity":
        r = cli._guard(checks.parity, n or 200, cli._log)
    elif which == "load":
        r = cli._guard(checks.load, n or 300, concurrency, via, cli._log)
    elif which == "rollback":
        r = cli._guard(checks.rollback, n or 100, cli._log)
    else:
        cli._fail("check must be parity, load or rollback")
    if not r["passed"]:
        raise typer.Exit(1)


@decision_app.command("reconcile")
def decision_reconcile(days: int = typer.Option(3, "--days")) -> None:
    """Log decisions from the endpoint's inference table that no caller logged."""
    from lau.decision import log

    cli = _cli()
    cli._guard(log.reconcile, days, cli._log)


@decision_app.command("explain")
def decision_explain(decision_id: str) -> None:
    """The adverse-action reasons and versions behind one decision."""
    from lau.decision import notices

    cli = _cli()
    found = cli._guard(notices.notice, decision_id)
    if found is None:
        cli._fail(f"no decision {decision_id}")
    _print(found)


# ---- rollouts --------------------------------------------------------------------------------------------------------
@rollout_app.command("list")
def rollout_list() -> None:
    """Rollouts, newest first, with their state."""
    from lau.decision import rollout

    for r in _cli()._guard(rollout.rollouts):
        _cli()._log(
            f"{r['rollout_id']}  {r['state']:<11}  v{r['model_version']}  "
            f"started {r['started_at']} by {r['started_by']}"
        )


@rollout_app.command("report")
def rollout_report(rollout_id: str) -> None:
    """Shadow report: serving decisions next to what the shadow champion would have decided."""
    from lau.decision import rollout

    _print(_cli()._guard(rollout.report, rollout_id))


@rollout_app.command("decide")
def rollout_decide(
    rollout_id: str,
    decision: str = typer.Option(..., "--decision", help="approve or reject"),
    note: str = typer.Option(..., "--note", help="what you checked in the shadow report"),
    approver: str = typer.Option("", "--approver", help="who decides (default: the OS user)"),
    as_json: bool = typer.Option(False, "--json", help="print one JSON ActionResult line"),
) -> None:
    """Record a decision on serving the champion in this rollout."""
    from lau.console import actions

    cli = _cli()
    cli._action_done(
        cli._guard(actions.rollout_decide, rollout_id, decision, note, approver or getpass.getuser()), as_json
    )


@rollout_app.command("serve")
def rollout_serve(
    rollout_id: str,
    by: str = typer.Option("", "--by"),
    as_json: bool = typer.Option(False, "--json", help="print one JSON ActionResult line"),
) -> None:
    """Make the approved champion in shadow the one that decides (promoter identity)."""
    from lau.console import actions

    cli = _cli()
    cli._action_done(cli._guard(actions.rollout_serve, rollout_id, by or getpass.getuser()), as_json)


@rollout_app.command("rollback")
def rollout_rollback(
    rollout_id: str,
    reason: str = typer.Option(..., "--reason"),
    by: str = typer.Option("", "--by"),
    as_json: bool = typer.Option(False, "--json", help="print one JSON ActionResult line"),
) -> None:
    """Return serving to the model (or legacy policy) that decided before this rollout. One person suffices."""
    from lau.console import actions

    cli = _cli()
    cli._action_done(cli._guard(actions.rollout_rollback, rollout_id, reason, by or getpass.getuser()), as_json)


# ---- loan status feed ------------------------------------------------------------------------------------------------
@feed_app.command("run")
def feed_run() -> None:
    """Write the simulated servicer's feed for the newest completed month, ingest new files, check maturation."""
    from lau.feedback import feed, production, servicer

    cli = _cli()
    cli._guard(servicer.run, cli._log)
    result = cli._guard(feed.ingest, cli._log)
    cli._guard(production.maturation_check, cli._log)
    if result["held"]:
        cli._fail(f"held for review: {', '.join(result['held'])} (lau feed release <file>)")


@feed_app.command("status")
def feed_status() -> None:
    """Files read, quarantined records, restatements and maturity of the production book."""
    from lau.feedback import feed
    from lau.store import get_store

    st = get_store("harness")
    out: dict = {"held": feed.held_files(), "pending": feed.pending_files()}
    for table in ("feed_files", "maturation_events"):
        if st.table_exists("ops", table):
            out[table] = st.query(f"SELECT * FROM {st.fq('ops', table)} ORDER BY 1 DESC LIMIT 5").to_dict("records")
    _print(out)


@feed_app.command("release")
def feed_release(feed_file: str, by: str = typer.Option("", "--by")) -> None:
    """After reviewing a held file's quarantine, ingest its valid records (the bad ones stay quarantined)."""
    from lau.feedback import feed

    cli = _cli()
    try:
        cli._guard(feed.release, feed_file, by or getpass.getuser(), cli._log)
    except ValueError as e:
        cli._fail(str(e))
