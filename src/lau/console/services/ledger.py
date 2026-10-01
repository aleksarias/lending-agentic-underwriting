"""The improvement ledger (ops.improvement_ledger): the verdict on whether the system is getting better."""

from __future__ import annotations

import pandas as pd

from lau.console import deps
from lau.console.services import models
from lau.console.util import AS_OF, iso, loads, num, read_table, text, ttl_cache

VERDICT_CODES = {"improved", "no_change", "not_best", "regressed", "insufficient_evidence"}


@ttl_cache(10)
def latest() -> dict | None:
    """The newest ledger row with JSON columns parsed, or None when the ledger has never been written."""
    df = read_table(deps.ui_store(), "ops", "improvement_ledger", ts=["computed_at"])
    cutoff = AS_OF.get()
    if len(df) and cutoff is not None:
        df = df[df["computed_at"] <= cutoff.tz_localize("UTC")]
    if df.empty:
        return None
    r = df.sort_values("computed_at").iloc[-1].to_dict()
    code = text(r.get("verdict_code")) or "insufficient_evidence"
    return {
        "code": code if code in VERDICT_CODES else "insufficient_evidence",
        "title": text(r.get("title")) or "",
        "detail": text(r.get("detail")) or "",
        "computed_at": r.get("computed_at"),
        "primary_benchmark": text(r.get("primary_benchmark")) or "",
        "active_definition": text(r.get("active_definition")),
        "best_known_key": text(r.get("best_known_key")),
        "best_known_label": text(r.get("best_known_label")),
        "newest_challenger_key": text(r.get("newest_challenger_key")),
        "newest_challenger_label": text(r.get("newest_challenger_label")),
        "serving_key": text(r.get("serving_key")),
        "lift_estimate": num(r.get("lift_estimate")),
        "lift_lo": num(r.get("lift_lo")),
        "lift_hi": num(r.get("lift_hi")),
        "guardrails": loads(r.get("guardrails_json"), []),
        "denominator": loads(r.get("denominator_json"), None),
    }


def _count_after(schema: str, table: str, column: str, ts) -> int:
    df = read_table(deps.ui_store(), schema, table, columns=[column], ts=[column])
    if df.empty or ts is None:
        return 0
    return int((df[column] > pd.Timestamp(ts)).sum())


@ttl_cache(15)
def stale_reason() -> str | None:
    """Why the latest verdict may be out of date: harness-written facts newer than the evidence run, else None."""
    row = latest()
    if row is None or row["computed_at"] is None:
        return None
    at = row["computed_at"]
    changes = []
    n = _count_after("ops", "evaluations", "ts", at)
    if n:
        changes.append(f"{n} new evaluation{'s' if n != 1 else ''}")
    n = _count_after("ops", "active_definition", "activated_at", at)
    if n:
        changes.append("a definition change")
    n = _count_after("ops", "data_version", "created_at", at)
    if n:
        changes.append("a data load")
    n = _count_after("production", "promotions", "ts", at)
    if n:
        changes.append(f"{n} promotion{'s' if n != 1 else ''}")
    if not changes:
        return None
    listed = ", ".join(changes[:-1]) + (" and " if len(changes) > 1 else "") + changes[-1]
    return f"Computed before {listed}. Run lau evidence run (or the lau-evidence job) to refresh it."


def verdict_brief() -> dict | None:
    """{code, title, stale} for the status bar."""
    row = latest()
    return None if row is None else {"code": row["code"], "title": row["title"], "stale": stale_reason() is not None}


def verdict_payload() -> dict | None:
    """Verdict (progress screen) from the newest ledger row."""
    row = latest()
    if row is None:
        return None
    lift = None
    if row["lift_estimate"] is not None:
        est = row["lift_estimate"]
        lift = {
            "estimate": est,
            "lo": row["lift_lo"] if row["lift_lo"] is not None else est,
            "hi": row["lift_hi"] if row["lift_hi"] is not None else est,
        }
    return {
        "code": row["code"],
        "title": row["title"],
        "detail": row["detail"],
        "computed_at": iso(row["computed_at"]),
        "primary_benchmark": row["primary_benchmark"],
        "best_known": models.ref_from_key(row["best_known_key"], row["best_known_label"]),
        "newest_challenger": models.ref_from_key(row["newest_challenger_key"], row["newest_challenger_label"]),
        "serving": models.ref_from_key(row["serving_key"]),
        "lift_vs_reference": lift,
        "stale_reason": stale_reason(),
    }
