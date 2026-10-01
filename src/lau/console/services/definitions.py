"""Definitions of default: refs, versions with activation history, plain-language text, diffs and sensitivity."""

from __future__ import annotations

from typing import Any

import pandas as pd

from lau.console import deps
from lau.console.util import integer, iso, loads, num, read_table, short, text, ttl_cache

# Display order for exclusions (the stored order is alphabetical).
_EXCLUSION_ORDER = ["fraud_confirmed", "deceased", "early_payoff"]


def _join(items: list[str], word: str, oxford: bool = False) -> str:
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} {word} {items[1]}"
    sep = f", {word} " if oxford else f" {word} "
    return ", ".join(items[:-1]) + sep + items[-1]


def _money(v: float) -> str:
    return f"${int(v):,}" if float(v).is_integer() else f"${v:,.2f}"


def summary_text(fields: dict) -> str:
    """Short label such as "60 DPD ever / 12 months"."""
    timing = "ever" if fields.get("delinquency_timing", "ever") == "ever" else "at end of window"
    return f"{fields.get('delinquency_threshold_dpd')} DPD {timing} / {fields.get('observation_window_months')} months"


def plain_language(f: dict) -> str:
    """A credit-risk reader's sentence for the definition, generated from its fields (no LLM)."""
    window = f.get("observation_window_months")
    when = (
        f"at any point in its first {window} months on book"
        if f.get("delinquency_timing", "ever") == "ever"
        else f"at the end of its first {window} months on book"
    )
    events = []
    if f.get("include_charge_off"):
        events.append("charged off")
    if f.get("include_settlement"):
        events.append("settled")
    if f.get("include_bankruptcy"):
        events.append("declared bankrupt")
    if f.get("include_forbearance_as_default"):
        events.append("placed in forbearance")
    first = f"A loan defaults if it reaches {f.get('delinquency_threshold_dpd')} days past due {when}"
    if events:
        first += ", or is " + _join(events, "or")
    parts = [first + "."]

    excl = f.get("exclusions") or []
    names = {
        "fraud_confirmed": "confirmed fraud",
        "deceased": "a death",
        "early_payoff": f"payoff in the first {f.get('early_payoff_within_months')} months",
    }
    shown = [names[e] for e in _EXCLUSION_ORDER if e in excl]
    parts.append(f"Loans with {_join(shown, 'or', oxford=True)} are excluded." if shown else "No loans are excluded.")

    seasoning = int(f.get("min_seasoning_months") or 0)
    if f.get("maturity_rule") == "censor":
        parts.append(f"Loans observed for less than {window} months are kept but marked as not yet mature.")
    elif seasoning and seasoning != window:
        parts.append(f"Loans with fewer than {seasoning} months on book are left out.")

    cure = f.get("cure_handling") or {}
    if cure.get("mode") == "cured_not_default":
        parts.append(
            f"A loan that stays current for {cure.get('cure_months_required')} months after a delinquency "
            "is treated as cured, not a default."
        )
    if f.get("custom_sql_predicate"):
        parts.append(f"A custom SQL rule also counts as default: {f['custom_sql_predicate']}.")
    material = num(f.get("balance_materiality_threshold"))
    if material:
        parts.append(f"Past-due amounts under {_money(material)} are ignored.")
    return " ".join(parts)


def _semantic_fields(full_json: Any) -> tuple[dict, Any]:
    """(fields, DefaultDefinition|None) from a stored definition JSON."""
    from lau.definition.schema import definition_from_dict

    raw = loads(full_json, {})
    try:
        defn = definition_from_dict(raw)
        return defn.semantic_dict(), defn
    except Exception:  # noqa: BLE001 - keep the row visible even if the schema moved on
        return {k: v for k, v in raw.items() if k != "metadata"}, None


@ttl_cache(30)
def _load() -> dict:
    """All known definitions plus the activation history (treat as read-only)."""
    st = deps.ui_store()
    dv = read_table(st, "ops", "definition_versions", ts=["created_at"])
    hist = read_table(st, "ops", "active_definition", order_by="activated_at", ts=["activated_at"])
    versions: dict[str, dict] = {}
    for r in dv.to_dict("records") if len(dv) else []:
        fields, defn = _semantic_fields(r.get("full_json"))
        meta = (loads(r.get("full_json"), {}) or {}).get("metadata", {})
        versions[str(r["definition_version"])] = {
            "version": str(r["definition_version"]),
            "name": text(r.get("name")) or text(meta.get("name")) or str(r["definition_version"])[:8],
            "description": text(r.get("description")) or text(meta.get("description")) or "",
            "fields": fields,
            "definition": defn,
            "created_at": r.get("created_at"),
            "created_by": text(r.get("created_by")),
        }
    history = [
        {
            "version": str(r["definition_version"]),
            "previous_version": text(r.get("previous_version")),
            "activated_at": r.get("activated_at"),
            "activated_by": text(r.get("activated_by")),
            "approval_id": text(r.get("approval_id")),
        }
        for r in (hist.to_dict("records") if len(hist) else [])
    ]
    return {"versions": versions, "history": history}


def active_version() -> str | None:
    hist = _load()["history"]
    return hist[-1]["version"] if hist else None


def known_versions() -> list[str]:
    return list(_load()["versions"])


def resolve_version(version: str | None) -> str | None:
    """Exact version or a unique prefix (the UI may pass the 8-character short form); None if unknown."""
    if not version:
        return None
    versions = _load()["versions"]
    if version in versions:
        return version
    hits = [v for v in versions if v.startswith(version)]
    return hits[0] if len(hits) == 1 else None


def resolve_or_404(version: str | None) -> str:
    """The requested definition (exact or unique prefix), the active one when none is given; 404 when unknown."""
    from fastapi import HTTPException

    if version:
        resolved = resolve_version(version)
        if resolved is None:
            raise HTTPException(status_code=404, detail="unknown definition version")
        return resolved
    return active_version() or ""


def definition_ref(version: str | None) -> dict | None:
    if not version:
        return None
    v = _load()["versions"].get(version)
    if v is None:
        return None
    f = v["fields"]
    return {
        "version": version,
        "short": short(version),
        "name": v["name"],
        "summary": summary_text(f),
        "dpd": int(f.get("delinquency_threshold_dpd") or 0),
        "timing": "ever" if f.get("delinquency_timing", "ever") == "ever" else "end_of_window",
        "window_months": int(f.get("observation_window_months") or 0),
    }


def definition_refs() -> list[dict]:
    """Every known definition, most recently active or created first."""
    order = sorted(_load()["versions"], key=lambda v: _sort_key(v), reverse=True)
    return [r for r in (definition_ref(v) for v in order) if r]


def definition_name(version: str | None) -> str | None:
    v = _load()["versions"].get(version or "")
    return v["name"] if v else None


def _latest_activation(version: str) -> tuple[int, dict] | None:
    hist = _load()["history"]
    for i in range(len(hist) - 1, -1, -1):
        if hist[i]["version"] == version:
            return i, hist[i]
    return None


def _sort_key(version: str) -> pd.Timestamp:
    found = _latest_activation(version)
    ts = found[1]["activated_at"] if found else _load()["versions"][version]["created_at"]
    return pd.Timestamp(ts) if ts is not None and not pd.isna(ts) else pd.Timestamp(0, tz="UTC")


def activated_at(version: str | None) -> Any:
    found = _latest_activation(version) if version else None
    return found[1]["activated_at"] if found else None


@ttl_cache(30)
def label_stats_by_version() -> dict[str, dict]:
    st = deps.ui_store()
    df = read_table(st, "ops", "label_stats", columns=["definition_version", "summary_json"])
    out: dict[str, dict] = {}
    for r in df.to_dict("records") if len(df) else []:
        s = loads(r["summary_json"], {}) or {}
        out[str(r["definition_version"])] = {
            "n_loans": integer(s.get("n_loans")) or 0,
            "n_eligible": integer(s.get("n_eligible")) or 0,
            "n_default": integer(s.get("n_default")) or 0,
            "default_rate": num(s.get("default_rate")) or 0.0,
            "exclusions": {str(k): int(v) for k, v in (s.get("exclusions") or {}).items()},
            "triggers": {str(k): int(v) for k, v in (s.get("triggers") or {}).items()},
        }
    return out


@ttl_cache(30)
def split_meta_by_version() -> dict[str, dict]:
    st = deps.ui_store()
    df = read_table(st, "labels", "split_meta")
    out: dict[str, dict] = {}
    for r in df.to_dict("records") if len(df) else []:
        n = loads(r.get("n_json"), {}) or {}
        rate = loads(r.get("default_rate_json"), {}) or {}
        out[str(r["definition_version"])] = {
            "train": [str(r.get("train_start")), str(r.get("train_end"))],
            "validation": [str(r.get("val_start")), str(r.get("val_end"))],
            "oot": [str(r.get("oot_start")), str(r.get("oot_end"))],
            "n": {str(k): int(v) for k, v in n.items()},
            "default_rate": {str(k): float(v) for k, v in rate.items()},
        }
    return out


def diff_vs_previous(version: str) -> list[dict]:
    """Field changes against the definition that was active before this one was (last) activated."""
    from lau.definition.registry import diff_definitions

    data = _load()
    found = _latest_activation(version)
    if found is None:
        return []
    idx, row = found
    prev = row["previous_version"] or (data["history"][idx - 1]["version"] if idx > 0 else None)
    cur = data["versions"].get(version)
    old = data["versions"].get(prev) if prev else None
    if cur is None or cur["definition"] is None or old is None or old["definition"] is None:
        return []
    return [{"field": f, "before": b, "after": a} for f, b, a in diff_definitions(old["definition"], cur["definition"])]


def definition_version_payload(version: str) -> dict | None:
    data = _load()
    v = data["versions"].get(version)
    if v is None:
        return None
    found = _latest_activation(version)
    is_active = found is not None and found[0] == len(data["history"]) - 1
    active_to = None
    if found and found[0] + 1 < len(data["history"]):
        active_to = iso(data["history"][found[0] + 1]["activated_at"])
    ref = definition_ref(version) or {}
    return {
        "version": version,
        "short": short(version),
        "name": v["name"],
        "summary": ref.get("summary", ""),
        "dpd": ref.get("dpd", 0),
        "timing": ref.get("timing", "ever"),
        "window_months": ref.get("window_months", 0),
        "description": v["description"],
        "plain_language": plain_language(v["fields"]),
        "fields": v["fields"],
        "created_at": iso(v["created_at"]),
        "active_from": iso(found[1]["activated_at"]) if found else None,
        "active_to": active_to,
        "is_active": bool(is_active),
        "activated_by": found[1]["activated_by"] if found else None,
        "approval_id": found[1]["approval_id"] if found else None,
        "label_stats": label_stats_by_version().get(version),
        "split": split_meta_by_version().get(version),
        "diff_vs_previous": diff_vs_previous(version),
    }


def all_definition_payloads() -> list[dict]:
    versions = sorted(_load()["versions"], key=_sort_key, reverse=True)
    return [p for p in (definition_version_payload(v) for v in versions) if p]


@ttl_cache(30)
def sensitivity() -> dict:
    """Default rate by calendar quarter under each benchmark definition (latest run of ops.definition_sensitivity)."""
    st = deps.ui_store()
    df = read_table(st, "ops", "definition_sensitivity", ts=["computed_at"])
    if df.empty:
        return {"computed_at": None, "series": []}
    if "run_id" in df.columns and df["run_id"].notna().any():
        latest_run = df.sort_values("computed_at")["run_id"].iloc[-1]
        df = df[df["run_id"] == latest_run]
    series = []
    for key, g in df.groupby("benchmark_key", sort=False):
        dpd = integer(g["benchmark_dpd"].iloc[0]) or 0
        points = [
            {"period": str(r["period"]), "default_rate": num(r["default_rate"]) or 0.0, "n": integer(r["n"]) or 0}
            for r in g.sort_values("period").to_dict("records")
        ]
        series.append({"definition_key": str(key), "label": f"{dpd} DPD", "dpd": dpd, "points": points})
    series.sort(key=lambda s: s["dpd"])
    return {"computed_at": iso(df["computed_at"].max()), "series": series}
