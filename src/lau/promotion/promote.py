"""Promotion: harness gate + red-team and compliance reports + recorded human approval -> champion.

Flow (`lau promote <candidate_model_version>`):
  1. candidate must carry red-team and compliance reports for this definition version (experiments.reports)
  2. harness promotion gate (the only holdout read) must pass  -> ops.gate_results
  3. a human approval row must exist                          -> ops.approvals  (`lau approve`)
  4. the PROMOTER identity copies the model version into <catalog>.<production>.pd_model, sets
     champion_<v8> (and `champion`, the serving alias, only if the version is the active definition),
     and writes production.promotions.
Champions are never deleted. When the definition changes, old champions are tagged
superseded_by_definition_change=true but keep serving until a new champion is approved.
"""

from __future__ import annotations

import getpass
import json
import uuid
from datetime import UTC, datetime

import pandas as pd

from lau.definition.registry import active_version
from lau.modeling import registry_io
from lau.store import get_store


class PromotionBlockedError(RuntimeError):
    pass


def required_reports(store, candidate_ref: str, version: str) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {"redteam": None, "compliance": None}
    if not store.table_exists("experiments", "reports"):
        return out
    df = store.query(
        f"SELECT kind, report_id, verdict, created_at FROM {store.fq('experiments', 'reports')} "
        f"WHERE candidate_ref = '{candidate_ref}' AND definition_version = '{version}' ORDER BY created_at DESC"
    )
    for kind in out:
        sub = df[df["kind"] == kind]
        if len(sub):
            out[kind] = sub.iloc[0].to_dict()
    return out


def record_approval(
    candidate_ref: str, decision: str, rationale: str, gate_id: str, version: str, approver: str | None = None
) -> str:
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be approve|reject")
    st = get_store("harness")
    approval_id = f"apr-{uuid.uuid4().hex[:10]}"
    st.write_df(
        "ops",
        "approvals",
        pd.DataFrame(
            [
                {
                    "approval_id": approval_id,
                    "candidate_ref": candidate_ref,
                    "definition_version": version,
                    "decision": decision,
                    "approver": approver or getpass.getuser(),
                    "rationale": rationale[:4000],
                    "gate_id": gate_id,
                    "ts": datetime.now(UTC),
                }
            ]
        ),
        mode="append",
    )
    return approval_id


def latest_approval(store, candidate_ref: str) -> dict | None:
    if not store.table_exists("ops", "approvals"):
        return None
    df = store.query(
        f"SELECT * FROM {store.fq('ops', 'approvals')} WHERE candidate_ref = '{candidate_ref}' ORDER BY ts DESC LIMIT 1"
    )
    return None if df.empty else df.iloc[0].to_dict()


def promote(candidate_mv: str, log=print) -> dict:
    """Runs as the promoter identity for the registry writes. Requires gate + reports + approval."""
    from lau.harness.gate import latest_gate

    reader = get_store("promoter")  # can read ops (approvals, gate_results) and experiments (reports)
    tags = registry_io.version_tags(registry_io.candidate_model_name(), candidate_mv, "promoter")
    version = tags.get("definition_version")
    if not version:
        raise PromotionBlockedError("candidate has no definition_version tag")
    ref = f"candidate:{candidate_mv}"
    reports = required_reports(reader, ref, version)
    missing = [k for k, v in reports.items() if v is None]
    if missing:
        raise PromotionBlockedError(f"missing reports: {missing}")
    if reports["compliance"]["verdict"] == "block":
        raise PromotionBlockedError("compliance finding is 'block'")
    gate = latest_gate(reader, ref)
    if not gate or not gate["passed"] or gate["definition_version"] != version:
        raise PromotionBlockedError("no passing harness gate for this candidate and definition version")
    approval = latest_approval(reader, ref)
    if not approval or approval["decision"] != "approve" or approval["gate_id"] != gate["gate_id"]:
        raise PromotionBlockedError("no human approval recorded for this candidate's latest gate result")

    prod = registry_io.production_model_name()
    with registry_io.mlflow_session("promoter") as c:
        try:
            c.create_registered_model(prod, tags={"project": "lau"})
        except Exception:  # noqa: BLE001, S110 - already exists
            pass
        mv = c.copy_model_version(f"models:/{registry_io.candidate_model_name()}/{candidate_mv}", prod)
        new_tags = {
            **tags,
            "lau_kind": "champion",
            "approval_id": approval["approval_id"],
            "gate_id": gate["gate_id"],
            "source_candidate_version": candidate_mv,
            "superseded_by_definition_change": "false",
            "status": "champion",
        }
        for k, v in new_tags.items():
            c.set_model_version_tag(prod, mv.version, k, str(v))
        # retire the previous champion of THIS definition (kept, not deleted)
        prev = None
        try:
            prev = c.get_model_version_by_alias(prod, registry_io.champion_alias(version))
            c.set_model_version_tag(prod, prev.version, "status", "retired")
        except Exception:  # noqa: BLE001, S110 - no previous champion for this definition
            pass
        c.set_registered_model_alias(prod, registry_io.champion_alias(version), mv.version)
        serving = version == active_version(reader)
        if serving:
            c.set_registered_model_alias(prod, registry_io.SERVING_ALIAS, mv.version)
    promo = {
        "promotion_id": f"promo-{uuid.uuid4().hex[:10]}",
        "ts": datetime.now(UTC),
        "definition_version": version,
        "production_model_version": str(mv.version),
        "candidate_model_version": candidate_mv,
        "previous_champion_version": None if prev is None else str(prev.version),
        "serving": serving,
        "approval_id": approval["approval_id"],
        "gate_id": gate["gate_id"],
        "reports_json": json.dumps({k: v["report_id"] for k, v in reports.items()}),
    }
    get_store("promoter").write_df("production", "promotions", pd.DataFrame([promo]), mode="append")
    log(
        f"promoted candidate v{candidate_mv} -> {prod} v{mv.version} as {registry_io.champion_alias(version)}"
        + (" and SERVING" if serving else " (not serving: definition not active)")
    )
    return promo


def mark_superseded(new_version: str) -> int:
    """Tag champions of other definition versions as superseded (never deleted). Returns count tagged."""
    prod = registry_io.production_model_name()
    n = 0
    try:
        with registry_io.mlflow_session("promoter") as c:
            for mv in c.search_model_versions(f"name = '{prod}'"):
                tags = dict(mv.tags)
                if (
                    tags.get("lau_kind") == "champion"
                    and tags.get("definition_version") != new_version
                    and tags.get("superseded_by_definition_change") != "true"
                ):
                    c.set_model_version_tag(prod, mv.version, "superseded_by_definition_change", "true")
                    c.set_model_version_tag(prod, mv.version, "superseded_by_definition", new_version)
                    n += 1
    except Exception as e:  # noqa: BLE001 - no production model yet
        if "not found" not in str(e).lower() and "does not exist" not in str(e).lower():
            raise
    return n
