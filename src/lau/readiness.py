"""Production readiness: the checklist in config/readiness.yaml, evidence the system gathers for each item, and the
sign-offs named people record (ops.signoffs).

Evidence is prerequisite material, never a substitute for a signature: an item is done only when every required role
has a current sign-off from a person and nobody has declined. Signing needs a person at a terminal (`lau readiness
sign`). Nothing here claims the system is compliant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from lau.settings import ROOT, get_settings
from lau.store import get_store


def _q(st, sql: str) -> pd.DataFrame:
    try:
        return st.query(sql)
    except Exception:  # noqa: BLE001 - evidence whose table does not exist yet is simply missing
        return pd.DataFrame()


def _latest_checks(st) -> dict[str, bool]:
    if not st.table_exists("ops", "release_checks"):
        return {}
    df = _q(st, f"SELECT * FROM {st.fq('ops', 'release_checks')} ORDER BY run_at")
    if df.empty:
        return {}
    last = df.drop_duplicates("check", keep="last")
    return {str(r["check"]): bool(r["passed"]) for r in last.to_dict("records")}


def evidence(store=None) -> dict[str, list[dict]]:
    """item id -> [{label, met, detail}] gathered from the system (no judgement about sufficiency)."""
    from lau.modeling import registry_io

    st = store or get_store("harness")
    s = get_settings()
    serving = None
    try:
        serving = registry_io.serving_model("harness")
    except Exception:  # noqa: BLE001 - no registry yet
        serving = None
    mv = str(serving["model_version"]) if serving else None
    checks = _latest_checks(st)
    out: dict[str, list[dict]] = {}

    import yaml

    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text()) or {}
    prod_host = str((((bundle.get("targets") or {}).get("prod") or {}).get("workspace") or {}).get("host") or "")
    masking = s.masking.get("enabled")
    out["real_data"] = [
        {"label": "Real data loaded", "met": False, "detail": "every table in this workspace is synthetic"},
        {
            "label": "PII masking on in production",
            "met": masking is not False,
            "detail": "config/masking.yaml: on in prod by default" if masking is None else f"enabled: {masking}",
        },
        {
            "label": "A production workspace is configured",
            "met": bool(prod_host) and "PLACEHOLDER" not in prod_host.upper(),
            "detail": prod_host or "none",
        },
    ]

    rollouts = (
        _q(st, f"SELECT * FROM {st.fq('production', 'rollouts')}")
        if st.table_exists("production", "rollouts")
        else pd.DataFrame()
    )
    served = rollouts[rollouts["event"] == "served"] if len(rollouts) else rollouts
    out["parallel_run"] = [
        {
            "label": "The serving champion went through a shadow rollout",
            "met": bool(mv and len(served) and mv in set(served["model_version"].astype(str))),
            "detail": f"serving v{mv}" if mv else "no model serves (the legacy policy decides)",
        }
    ]

    reports = (
        _q(st, f"SELECT report_id FROM {st.fq('experiments', 'reports')}")
        if st.table_exists("experiments", "reports")
        else pd.DataFrame()
    )
    have = set(reports["report_id"].astype(str)) if len(reports) else set()
    out["model_validation"] = [
        {
            "label": "Model documentation for the serving champion",
            "met": bool(mv and f"md-{mv}" in have),
            "detail": f"lau report model {mv}" if mv else "no model serves",
        },
        {
            "label": "Training-serving parity check passed",
            "met": checks.get("parity") is True,
            "detail": "lau decision check parity",
        },
        {
            "label": "Production evidence computed",
            "met": st.table_exists("ops", "production_evidence"),
            "detail": "matured loans, by model, band and vintage",
        },
    ]

    unmapped = None
    if mv:
        try:
            from lau.decision.reasons import UNMAPPED, statement_for

            model = registry_io.load_pd_model(f"models:/{registry_io.production_model_name()}/{mv}", "harness")
            unmapped = [f for f in model.features if statement_for(f)[0] == UNMAPPED]
        except Exception:  # noqa: BLE001 - reported as not met
            unmapped = None
    fair = (
        _q(st, f"SELECT * FROM {st.fq('ops', 'decision_fairness')}")
        if st.table_exists("ops", "decision_fairness")
        else pd.DataFrame()
    )
    latest_fair = fair[fair["run_id"] == fair.sort_values("computed_at")["run_id"].iloc[-1]] if len(fair) else fair
    below = (
        int(latest_fair[latest_fair["method"] != "synthetic_truth"]["below_threshold"].astype(bool).sum())
        if len(latest_fair)
        else None
    )
    out["compliance"] = [
        {
            "label": "Every input of the serving model has an approved reason statement",
            "met": unmapped == [],
            "detail": "no model serves" if unmapped is None else (", ".join(unmapped) or "all mapped"),
        },
        {
            "label": "Fairness on actual decisions measured, no group below the threshold",
            "met": below == 0,
            "detail": "not measured yet" if below is None else f"{below} group(s) below",
        },
    ]

    out["security_operations"] = [
        {
            "label": "Load check passed",
            "met": checks.get("load") is True,
            "detail": "lau decision check load (against the endpoint for real use)",
        },
        {
            "label": "Rollback drill passed",
            "met": checks.get("rollback") is True,
            "detail": "lau decision check rollback",
        },
        {"label": "Runbook written", "met": (ROOT / "docs" / "runbook.md").exists(), "detail": "docs/runbook.md"},
    ]
    out["reject_inference"] = [
        {
            "label": "Experiment designed",
            "met": (ROOT / "docs" / "reject-inference.md").exists(),
            "detail": "docs/reject-inference.md",
        },
    ]
    return out


# ---- sign-offs -----------------------------------------------------------------------------------------------------
def items() -> list[dict]:
    return list(get_settings().readiness["items"])


def signoffs(store=None) -> pd.DataFrame:
    st = store or get_store("harness")
    if not st.table_exists("ops", "signoffs"):
        return pd.DataFrame(columns=["signoff_id", "item_id", "role", "signer", "decision", "note", "ts"])
    return _q(st, f"SELECT * FROM {st.fq('ops', 'signoffs')} ORDER BY ts")


def record(item_id: str, role: str, signer: str, decision: str, note: str) -> dict:
    item = next((i for i in items() if i["id"] == item_id), None)
    if item is None:
        raise ValueError(f"unknown checklist item {item_id}")
    if role not in item["signers"]:
        raise ValueError(f"{item_id} is signed by {', '.join(item['signers'])}, not {role}")
    if decision not in ("sign", "decline", "revoke"):
        raise ValueError("decision must be sign, decline or revoke")
    if len(note.strip()) < 20:
        raise ValueError("a note of at least 20 characters is required: what you reviewed")
    row = {
        "signoff_id": f"so-{uuid.uuid4().hex[:10]}",
        "item_id": item_id,
        "role": role,
        "signer": signer,
        "decision": decision,
        "note": note.strip()[:4000],
        "ts": datetime.now(UTC).replace(tzinfo=None),
    }
    get_store("harness").write_df("ops", "signoffs", pd.DataFrame([row]), mode="append")
    return row


def compute(ctx) -> pd.DataFrame:
    """Evidence step `readiness_evidence`: the checklist evidence as rows, so the console reads it without models."""
    rows = [
        {"item_id": item_id, "label": e["label"], "met": bool(e["met"]), "detail": str(e["detail"])}
        for item_id, found in evidence(ctx.store).items()
        for e in found
    ]
    out = pd.DataFrame(rows)
    out.insert(0, "run_id", ctx.run_id)
    out.insert(0, "computed_at", ctx.computed_at)
    return out


def stored_evidence(store) -> dict[str, list[dict]] | None:
    """The latest readiness evidence run (console), or None before the first one."""
    if not store.table_exists("ops", "readiness_evidence"):
        return None
    t = store.fq("ops", "readiness_evidence")
    df = _q(store, f"SELECT * FROM {t} WHERE run_id = (SELECT run_id FROM {t} ORDER BY computed_at DESC LIMIT 1)")
    out: dict[str, list[dict]] = {}
    for r in df.to_dict("records"):
        out.setdefault(str(r["item_id"]), []).append(
            {"label": str(r["label"]), "met": bool(r["met"]), "detail": str(r["detail"])}
        )
    return out


def status(store=None, evidence_rows: dict[str, list[dict]] | None = None) -> dict:
    """Checklist with evidence and sign-offs. An item is done when every role's latest decision is a signature."""
    ev = evidence_rows if evidence_rows is not None else evidence(store)
    so = signoffs(store)
    out = []
    for item in items():
        mine = so[so["item_id"] == item["id"]] if len(so) else so
        latest = mine.drop_duplicates("role", keep="last") if len(mine) else mine
        by_role = {str(r["role"]): r for r in latest.to_dict("records")} if len(latest) else {}
        roles = [
            {
                "role": role,
                "decision": by_role[role]["decision"] if role in by_role else None,
                "signer": by_role[role]["signer"] if role in by_role else None,
                "ts": by_role[role]["ts"] if role in by_role else None,
                "note": by_role[role]["note"] if role in by_role else None,
            }
            for role in item["signers"]
        ]
        declined = [r["role"] for r in roles if r["decision"] == "decline"]
        signed = all(r["decision"] == "sign" for r in roles)
        out.append(
            {
                **{k: item[k] for k in ("id", "title", "detail")},
                "evidence": ev.get(item["id"], []),
                "signoffs": roles,
                "state": "declined" if declined else ("signed" if signed else "open"),
            }
        )
    ready = all(i["state"] == "signed" for i in out)
    return {
        "items": out,
        "ready": ready,
        "statement": (
            "Every item is signed by its named reviewers."
            if ready
            else f"{sum(i['state'] != 'signed' for i in out)} of {len(out)} items still need sign-off. The system does "
            "not decide on real applications until all are signed, and it does not claim compliance on its own."
        ),
    }


def runbook_path() -> Path:
    return ROOT / "docs" / "runbook.md"
