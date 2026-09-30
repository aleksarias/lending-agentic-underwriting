"""Agent reports (experiments.reports). Lists read metadata only; the markdown body is fetched one report at a time."""

from __future__ import annotations

import pandas as pd

from lau.console import deps
from lau.console.util import iso, read_table, sql_str, text, ttl_cache

_META_COLS = [
    "report_id",
    "cycle_id",
    "definition_version",
    "author",
    "kind",
    "title",
    "candidate_ref",
    "verdict",
    "created_at",
]


@ttl_cache(30)
def reports() -> pd.DataFrame:
    """Report metadata, newest first (no bodies)."""
    df = read_table(deps.ui_store(), "experiments", "reports", columns=_META_COLS, ts=["created_at"])
    return df.sort_values("created_at", ascending=False).reset_index(drop=True) if len(df) else df


def meta(r: dict) -> dict:
    """ReportMeta from a row ('' means not set for candidate_ref and verdict)."""
    return {
        "report_id": str(r["report_id"]),
        "cycle_id": str(text(r.get("cycle_id")) or ""),
        "author": str(text(r.get("author")) or ""),
        "kind": str(text(r.get("kind")) or ""),
        "title": str(text(r.get("title")) or ""),
        "verdict": text(r.get("verdict")),
        "candidate_ref": text(r.get("candidate_ref")),
        "created_at": iso(r["created_at"]),
        "definition_version": str(text(r.get("definition_version")) or ""),
    }


def list_meta(kind: str | None = None, cycle_id: str | None = None, candidate_ref: str | None = None) -> list[dict]:
    df = reports()
    if df.empty:
        return []
    if kind:
        df = df[df["kind"] == kind]
    if cycle_id:
        df = df[df["cycle_id"] == cycle_id]
    if candidate_ref:
        df = df[df["candidate_ref"] == candidate_ref]
    return [meta(r) for r in df.head(500).to_dict("records")]


def for_cycle(cycle_id: str) -> list[dict]:
    return list_meta(cycle_id=cycle_id)


def for_candidate(candidate_ref: str) -> list[dict]:
    return list_meta(candidate_ref=candidate_ref)


def report_with_body(report_id: str) -> dict | None:
    df = read_table(
        deps.ui_store(),
        "experiments",
        "reports",
        where=f"report_id = {sql_str(report_id)}",
        limit=1,
        ts=["created_at"],
    )
    if df.empty:
        return None
    r = df.iloc[0].to_dict()
    return {**meta(r), "body": str(text(r.get("body")) or "")}


def review_verdicts(candidate_ref: str) -> dict[str, dict | None]:
    """Latest red-team and compliance report (meta) for a candidate ref, or None when missing."""
    out: dict[str, dict | None] = {"redteam": None, "compliance": None}
    df = reports()
    if df.empty:
        return out
    mine = df[df["candidate_ref"] == candidate_ref]
    for kind in out:
        hit = mine[mine["kind"] == kind]
        if len(hit):
            out[kind] = meta(hit.iloc[0].to_dict())
    return out
