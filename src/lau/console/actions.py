"""Human actions behind the console and the CLI: run the holdout gate, record a decision, promote, stop a cycle,
acknowledge an alert. Each returns an ActionResult dict: {ok, message, ref}.

The functions run in-process against the configured backend (the CLI on Databricks; the console on a fixture lake).
A console that mirrors the workspace (LAU_CONSOLE_MIRROR=1) reads a local copy, so `dispatch` runs the same action
through the `lau` CLI on the Databricks backend instead; the write therefore lands in the workspace with the
harness or promoter identity, and the CLI publishes a fresh console snapshot when it is done.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime

import pandas as pd

ACTIONS = ("gate", "decide", "promote", "stop", "ack")


def _ok(message: str, ref: str | None = None) -> dict:
    return {"ok": True, "message": message, "ref": ref}


def _no(message: str, ref: str | None = None) -> dict:
    return {"ok": False, "message": message, "ref": ref}


def mirror_mode() -> bool:
    return os.environ.get("LAU_CONSOLE_MIRROR") == "1"


def model_version_of(candidate_ref: str) -> str:
    prefix, _, version = candidate_ref.partition(":")
    if prefix != "candidate" or not version.isdigit():
        raise ValueError(f"not a candidate ref: {candidate_ref}")
    return version


# ---------------------------------------------------------------------------------------------------- actions
def run_gate(candidate_ref: str) -> dict:
    """Holdout promotion gate for a validated candidate (one of the definition's limited holdout reads)."""
    from lau.harness.gate import promotion_gate
    from lau.modeling import registry_io

    mv = model_version_of(candidate_ref)
    tags = registry_io.version_tags(registry_io.candidate_model_name(), mv, "harness")
    version = tags.get("definition_version")
    if not version:
        return _no(f"{candidate_ref} has no definition_version tag", candidate_ref)
    model = registry_io.load_pd_model(registry_io.candidate_uri(mv), "harness")
    result = promotion_gate(model, version, candidate_ref)
    failed = [k for k, v in (result.get("checks") or {}).items() if not v]
    if result.get("passed"):
        return _ok(
            f"Holdout gate passed (holdout AUC {result['holdout']['auc']:.4f}, reference "
            f"{(result['reference'].get('holdout_auc') or 0):.4f}). A person can now approve or reject.",
            str(result.get("gate_id")),
        )
    return _no(
        f"Holdout gate failed: {', '.join(failed) or 'see the checks'}. Nothing can be promoted.",
        str(result.get("gate_id")),
    )


def decide(candidate_ref: str, decision: str, rationale: str, approver: str) -> dict:
    """Record a person's approve/reject decision on the candidate's latest passing gate result."""
    from lau.governance.approvals import ApprovalError, required, tally
    from lau.harness.gate import latest_gate
    from lau.promotion.promote import gate_decisions, record_approval
    from lau.store import get_store

    if decision not in ("approve", "reject"):
        return _no("decision must be approve or reject", candidate_ref)
    if len((rationale or "").strip()) < 10:
        return _no("a rationale of at least 10 characters is required", candidate_ref)
    st = get_store("harness")
    gate = latest_gate(st, candidate_ref)
    if not gate or not gate.get("passed"):
        return _no("No passing holdout gate result to decide on. Run the gate first.", candidate_ref)
    try:
        approval_id = record_approval(
            candidate_ref, decision, rationale.strip(), str(gate["gate_id"]), str(gate["definition_version"]), approver
        )
    except ApprovalError as e:
        return _no(str(e), candidate_ref)
    counts = tally(gate_decisions(st, candidate_ref, str(gate["gate_id"])))
    need = required("promotion")
    if decision == "reject":
        return _ok(
            f"Rejected and recorded as {approval_id}. The candidate cannot be promoted on this gate result.",
            approval_id,
        )
    if counts["count"] < need:
        return _ok(
            f"Approved and recorded as {approval_id}: {counts['count']} of {need} approvals. "
            "Another person must approve before promotion.",
            approval_id,
        )
    return _ok(f"Approved and recorded as {approval_id}. It can now be promoted.", approval_id)


def promote(candidate_ref: str) -> dict:
    """Promote an approved candidate (the promoter identity writes production)."""
    from lau.promotion.promote import PromotionBlockedError
    from lau.promotion.promote import promote as do_promote

    try:
        promo = do_promote(model_version_of(candidate_ref), log=lambda _m: None)
    except PromotionBlockedError as e:
        return _no(f"Promotion blocked: {e}", candidate_ref)
    serving = " It is now serving." if promo.get("serving") else " It is champion for its definition but not serving."
    return _ok(f"Promoted to production v{promo['production_model_version']}.{serving}", str(promo["promotion_id"]))


def stop(cycle_id: str, reason: str, by: str) -> dict:
    from lau.agents.orchestrator import request_stop

    request_stop(cycle_id, reason or f"stopped from the console by {by}", requested_by=by)
    return _ok(f"Stop requested. Cycle {cycle_id} stops before its next agent run; the current run finishes.", cycle_id)


def ack(alert_id: str, note: str, by: str) -> dict:
    from lau.console.services import ops
    from lau.store import get_store

    if alert_id not in {a["id"] for a in ops.alerts()}:
        return _no("unknown alert", alert_id)
    if alert_id in ops.acks():
        return _ok("Already acknowledged.", alert_id)
    row = {"alert_id": alert_id, "acked_at": datetime.now(UTC), "acked_by": by, "note": (note or "").strip()[:1000]}
    get_store("harness").write_df("ops", "alert_acks", pd.DataFrame([row]), mode="append")
    return _ok(f"Acknowledged by {by}. The alert stays in the history.", alert_id)


# --------------------------------------------------------------------------------------------------- dispatch
def _cli_args(name: str, kw: dict) -> list[str]:
    if name == "gate":
        return ["gate", kw["candidate_ref"]]
    if name == "decide":
        return [
            "decide",
            kw["candidate_ref"],
            "--decision",
            kw["decision"],
            "--rationale",
            kw["rationale"],
            "--approver",
            kw["approver"],
        ]
    if name == "promote":
        return ["promote-approved", kw["candidate_ref"]]
    if name == "stop":
        return ["stop-cycle", kw["cycle_id"], "--reason", kw.get("reason") or "", "--by", kw["by"]]
    if name == "ack":
        return ["ack-alert", kw["alert_id"], "--note", kw.get("note") or "", "--by", kw["by"]]
    raise ValueError(f"unknown action {name}")


def run_cli(args: list[str], timeout_s: int = 1800) -> dict:
    """Run `lau <args> --json` on the Databricks backend and return its ActionResult."""
    env = {k: v for k, v in os.environ.items() if k not in ("LAU_LOCAL_LAKE", "LAU_CONSOLE_MIRROR", "LAU_ENV_FILE")}
    env["LAU_BACKEND"] = "databricks"
    try:
        proc = subprocess.run(  # noqa: S603 - fixed program, arguments are passed as a list
            [sys.executable, "-m", "lau.cli", *args, "--json"],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _no("The action did not finish in time; check the workspace before retrying.")
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and '"ok"' in line:
            try:
                return json.loads(line)
            except ValueError:
                break
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
    return _no("The action failed: " + " ".join(tail)[:400])


def dispatch(name: str, **kw) -> dict:
    """Run an action in-process, or through the CLI on Databricks when the console mirrors the workspace."""
    if mirror_mode():
        result = run_cli(_cli_args(name, kw))
        from lau.console.snapshot import mirror

        m = mirror()
        if m is not None:
            m.request_sync()
        return result
    fn = {"gate": run_gate, "decide": decide, "promote": promote, "stop": stop, "ack": ack}[name]
    return fn(**kw)
