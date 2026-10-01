"""Entry point for Databricks jobs (`lau-job <task>`). Same code paths as the CLI; non-interactive."""

from __future__ import annotations

import os
import sys


def _bootstrap_runtime() -> None:
    """On Databricks, the job's run_as identity (harness) authenticates natively; secrets come from scope `lau`."""
    if not os.environ.get("DATABRICKS_RUNTIME_VERSION"):
        return
    os.environ.setdefault("LAU_RUNTIME_ROLE", "harness")
    try:
        from databricks.sdk.runtime import dbutils  # type: ignore[attr-defined]

        for env_key, secret_key in (
            ("ANTHROPIC_API_KEY", "anthropic_api_key"),
            ("ANTHROPIC_WORKSPACE_ID", "anthropic_workspace_id"),
            ("LAU_AGENT_CLIENT_ID", "agent_client_id"),
            ("LAU_AGENT_CLIENT_SECRET", "agent_client_secret"),
            ("LAU_UI_CLIENT_ID", "ui_client_id"),  # the console snapshot reads as the console's own identity
            ("LAU_UI_CLIENT_SECRET", "ui_client_secret"),
        ):
            if not os.environ.get(env_key):
                try:
                    os.environ[env_key] = dbutils.secrets.get("lau", secret_key)
                except Exception:  # noqa: BLE001, S110 - optional secrets; tasks that need them fail clearly
                    pass
    except ImportError:
        pass


def _paths_from_args(argv: list[str]) -> list[str]:
    """`--root <dir>`: the deployed bundle files (config/ is read from there). Reports go to a writable volume."""
    if "--root" in argv:
        i = argv.index("--root")
        root = argv[i + 1]
        argv = argv[:i] + argv[i + 2 :]
        os.environ.setdefault("LAU_ROOT", root)
        os.environ.setdefault("LAU_CONFIG_DIR", os.path.join(root, "config"))
        os.environ.setdefault("LAU_STATE_DIR", os.path.join(root, ".lau"))
    return argv


def main() -> None:
    sys.argv = _paths_from_args(sys.argv)
    _bootstrap_runtime()
    if os.environ.get("DATABRICKS_RUNTIME_VERSION") and "LAU_REPORTS_DIR" not in os.environ:
        from lau.settings import get_settings

        s = get_settings()
        os.environ["LAU_REPORTS_DIR"] = f"/Volumes/{s.catalog}/{s.schema('ops')}/landing/reports"
    task = sys.argv[1] if len(sys.argv) > 1 else ""
    if task == "definition-sync":
        from lau.pipeline import definition_ops as ops

        p = ops.plan(with_impact=False)
        if p.is_noop:
            print("definition unchanged; nothing to do")
            return
        ops.apply(confirm=None, run_cycle=False)  # raises ApprovalRequiredError without a recorded approval
    elif task == "decisions":
        from lau.decision import log as decision_log
        from lau.decision import traffic

        try:
            traffic.originate()  # one simulated month of synthetic applications, decided by the live decision model
        except traffic.NoDecisionModelError as e:
            print(f"no synthetic traffic today: {e}")  # until a person approves a policy and a build exists
            return
        decision_log.reconcile()  # decisions the endpoint made for anyone else (its inference table)
    elif task == "feedback":
        from lau.feedback import feed, production, servicer

        servicer.run()  # the simulated servicer's feed for the newest completed simulated month (once)
        result = feed.ingest()  # expectations, quarantine, bitemporal history, restatements
        production.maturation_check()  # newly matured loans queue an improvement cycle
        if result["held"]:
            raise SystemExit(f"feed file(s) held for review: {result['held']} (lau feed release <file>)")
    elif task == "shadow":
        from lau.promotion.shadow import run_shadow

        run_shadow()
    elif task == "monitor":
        from lau.promotion.monitor import run_monitor

        run_monitor()
    elif task == "console-snapshot":
        from lau.console.snapshot import publish

        publish(source="job")
    elif task == "evidence":
        from lau.evidence.run import run_all

        run_all()  # raises EvidenceRunError (the job fails visibly) if any step fails
    elif task == "run-cycle-if-queued":
        from lau.agents.orchestrator import run_cycle_sync
        from lau.store import get_store

        st = get_store("harness")
        q = (
            st.query(f"SELECT count(*) AS n FROM {st.fq('ops', 'cycle_queue')} WHERE status = 'queued'")
            if st.table_exists("ops", "cycle_queue")
            else None
        )
        if q is None or int(q["n"].iloc[0]) == 0:
            print("no queued cycle")
            return
        run_cycle_sync(reason="queued")
    else:
        raise SystemExit(f"unknown task {task!r}")


if __name__ == "__main__":
    main()
