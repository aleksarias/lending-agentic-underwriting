"""One timeline assembled from the tables that record what happened (no event table exists; nothing is duplicated).

Sources: definition activations and approvals, data loads, pipeline stage runs, cycles, evaluations, holdout gates,
promotion approvals, promotions, alerts, config changes, agent reports and benchmark runs.
"""

from __future__ import annotations

import pandas as pd

from lau.console import deps
from lau.console.services import definitions as defs
from lau.console.services import evals, models, ops, reports
from lau.console.util import boolean, iso, num, read_table, short, text, ttl_cache

EVENT_TYPES = [
    "definition_activated",
    "data_loaded",
    "stage_built",
    "stage_failed",
    "cycle_started",
    "cycle_finished",
    "evaluation",
    "gate",
    "approval",
    "promotion",
    "rollback",
    "alert",
    "budget_stop",
    "config_changed",
    "report",
    "benchmark",
]
AUTHOR_LABELS = {
    "planner": "Planner",
    "profiler": "Profiler",
    "feature": "Feature",
    "modeling": "Modeling",
    "redteam": "Red team",
    "compliance": "Compliance",
    "curator": "Curator",
}
# Too frequent to headline the overview; still on the History timeline.
QUIET_TYPES = {"stage_built", "benchmark", "config_changed"}


def _ev(
    type_: str,
    ts,
    title: str,
    ident: str,
    *,
    detail: str | None = None,
    definition_version: str | None = None,
    actor: str | None = None,
    tone: str = "neutral",
    href: str | None = None,
) -> dict | None:
    if ts is None or pd.isna(ts):
        return None
    return {
        "id": f"{type_}:{ident}",
        "ts": iso(ts),
        "type": type_,
        "title": title,
        "detail": detail,
        "definition_version": definition_version,
        "actor": actor,
        "tone": tone,
        "href": href,
        "_ts": pd.Timestamp(ts),
    }


def _def_label(version: str | None) -> str:
    ref = defs.definition_ref(version)
    return f"{ref['summary']} ({ref['short']})" if ref else (short(version) or "unknown definition")


def _definition_events() -> list[dict]:
    out = []
    for h in defs._load()["history"]:
        v = h["version"]
        out.append(
            _ev(
                "definition_activated",
                h["activated_at"],
                f"Definition of default changed to {_def_label(v)}",
                f"{v}:{iso(h['activated_at'])}",
                detail=f"Previously {_def_label(h['previous_version'])}" if h.get("previous_version") else None,
                definition_version=v,
                actor=h.get("activated_by"),
                tone="accent",
                href=f"/definitions/{v}",
            )
        )
    for a in evals.definition_approval_records():
        out.append(
            _ev(
                "approval",
                pd.Timestamp(a["ts"]) if a["ts"] else None,
                f"Definition change to {_def_label(a['ref'])} approved",
                a["approval_id"],
                definition_version=a["ref"],
                actor=a["approver"],
                tone="good",
                href=f"/definitions/{a['ref']}",
            )
        )
    return out


def _data_events() -> list[dict]:
    df = ops.data_versions()
    out = []
    for r in df.to_dict("records") if len(df) else []:
        n = r.get("n_applications")
        out.append(
            _ev(
                "data_loaded",
                r["created_at"],
                f"Data version {short(str(r['data_version']))} loaded",
                f"{r['data_version']}:{iso(r['created_at'])}",  # the same version can be loaded more than once
                detail=(
                    f"{int(n):,} applications, performance through {r.get('as_of_month')}"
                    if num(n) is not None
                    else None
                ),
                tone="neutral",
            )
        )
    return out


def _stage_events() -> list[dict]:
    df = ops.pipeline_rows()
    out = []
    for r in df.to_dict("records") if len(df) else []:
        failed = str(r.get("status")) == "failed"
        if str(r.get("status")) not in ("success", "failed"):
            continue
        out.append(
            _ev(
                "stage_failed" if failed else "stage_built",
                r.get("finished_at") or r.get("started_at"),
                f"Pipeline stage {r['stage']} {'failed' if failed else 'rebuilt'}",
                f"{r['stage']}:{r['definition_version']}:{iso(r['started_at'])}",
                definition_version=text(r.get("definition_version")),
                tone="crit" if failed else "neutral",
                href="/definitions/" + str(r["definition_version"]) if r.get("definition_version") else None,
            )
        )
    return out


def _cycle_events() -> list[dict]:
    out = []
    for r in ops.cycles().to_dict("records") if len(ops.cycles()) else []:
        s = ops.cycle_summary(r)
        cid = s["cycle_id"]
        out.append(
            _ev(
                "cycle_started",
                r["started_at"],
                f"Improvement cycle started: {s['reason'] or 'scheduled'}",
                cid,
                definition_version=s["definition_version"],
                tone="neutral",
                href=f"/history/cycles/{cid}",
            )
        )
        if s["status"] in ("running",):
            continue
        end = ops.cycle_finished_at(cid)
        stop = s["stop_reason"] or ""
        if s["status"] == "stopped_budget" or "budget" in stop.lower():
            out.append(
                _ev(
                    "budget_stop",
                    end,
                    f"Cycle stopped by a budget cap: {stop}",
                    cid,
                    definition_version=s["definition_version"],
                    tone="warn",
                    href=f"/history/cycles/{cid}",
                )
            )
            continue
        if s["challenger"]:
            passed = s["challenger_passed_validation"]
            title = f"Cycle finished: challenger v{s['challenger']} " + (
                "passed validation" if passed else "did not pass validation"
            )
            tone = "good" if passed else "warn"
        else:
            title, tone = f"Cycle finished ({s['status'].replace('_', ' ')}) with no challenger", "neutral"
        if s["status"] not in ("completed",):
            title, tone = f"Cycle {s['status'].replace('_', ' ')}: {stop or 'no reason recorded'}", "warn"
        verdicts = [f"red team {s['redteam_verdict']}" if s["redteam_verdict"] else None]
        verdicts.append(f"compliance {s['compliance_verdict']}" if s["compliance_verdict"] else None)
        cost = f"${s['anthropic_usd']:.2f} agent spend" if s["anthropic_usd"] is not None else None
        detail = "; ".join(x for x in [*verdicts, cost] if x) or None
        out.append(
            _ev(
                "cycle_finished",
                end,
                title,
                cid,
                detail=detail,
                definition_version=s["definition_version"],
                tone=tone,
                href=f"/history/cycles/{cid}",
            )
        )
    return out


def _evaluation_title(ref: str, passed: bool) -> str:
    model = models.ref_for_candidate(ref)
    if ref.startswith("baseline:"):
        return f"Baseline {model['label']} evaluated as the reference for its definition"
    return f"{model['label']} " + ("passed validation" if passed else "did not pass validation")


def _evaluation_events() -> list[dict]:
    df = evals.evaluations()
    out = []
    for r in df.to_dict("records") if len(df) else []:
        passed = bool(boolean(r.get("passed_validation")))
        auc, ref = num(r.get("val_auc")), num(r.get("reference_auc"))
        detail = f"validation AUC {auc:.4f}" if auc is not None else None
        if detail and ref is not None:
            detail += f" vs reference {ref:.4f}; required margin {num(r.get('required_margin')) or 0:.4f}"
        out.append(
            _ev(
                "evaluation",
                r["ts"],
                _evaluation_title(str(r["candidate_ref"]), passed),
                str(r["eval_id"]),
                detail=detail,
                definition_version=text(r.get("definition_version")),
                actor="harness",
                tone="good" if passed else "warn",
                href=f"/performance/evaluations/{r['eval_id']}",
            )
        )
    return out


def _gate_events() -> list[dict]:
    df = evals.gates()
    out = []
    for r in df.to_dict("records") if len(df) else []:
        passed = bool(boolean(r.get("passed")))
        ref = str(r["candidate_ref"])
        out.append(
            _ev(
                "gate",
                r["ts"],
                f"Holdout gate {'passed' if passed else 'failed'} for {models.ref_for_candidate(ref)['label']}",
                str(r["gate_id"]),
                detail=f"holdout AUC {num(r.get('holdout_auc')) or 0:.4f} vs reference "
                f"{num(r.get('reference_holdout_auc')) or 0:.4f}",
                definition_version=text(r.get("definition_version")),
                actor="harness",
                tone="good" if passed else "crit",
                href=f"/approvals/{ref}",
            )
        )
    return out


def _approval_events() -> list[dict]:
    df = evals.promotion_approvals()
    out = []
    for r in df.to_dict("records") if len(df) else []:
        ref = str(r["candidate_ref"])
        approve = str(r.get("decision")) == "approve"
        out.append(
            _ev(
                "approval",
                r["ts"],
                f"{models.ref_for_candidate(ref)['label']} {'approved' if approve else 'rejected'} for promotion",
                str(r["approval_id"]),
                detail=(text(r.get("rationale")) or "")[:300] or None,
                definition_version=text(r.get("definition_version")),
                actor=text(r.get("approver")),
                tone="good" if approve else "warn",
                href=f"/approvals/{ref}",
            )
        )
    return out


def _promotion_events() -> list[dict]:
    df = models.promotions()
    out = []
    _, prod = models.names()
    for r in df.to_dict("records") if len(df) else []:
        serving = bool(boolean(r.get("serving")))
        out.append(
            _ev(
                "promotion",
                r["ts"],
                f"Candidate v{r['candidate_model_version']} promoted to champion "
                f"(production v{r['production_model_version']})" + (", now serving" if serving else ""),
                str(r["promotion_id"]),
                detail=f"replaces production v{r['previous_champion_version']}"
                if text(r.get("previous_champion_version"))
                else None,
                definition_version=text(r.get("definition_version")),
                tone="accent",
                href=f"/models/{prod}/{r['production_model_version']}",
            )
        )
    return out


def _alert_events() -> list[dict]:
    out = []
    for a in ops.alerts():
        out.append(
            _ev(
                "alert",
                pd.Timestamp(a["ts"]),
                f"{a['severity'].capitalize()} alert: {ops.alert_title(a['kind'], a['subject'], a['value'])}",
                a["id"],
                detail=None,
                definition_version=a["definition_version"],
                actor="monitor",
                tone="crit" if a["severity"] == "high" else "warn",
                href="/alerts",
            )
        )
    return out


def _config_events() -> list[dict]:
    df = ops.config_versions()
    out = []
    if df.empty:
        return out
    df = df.sort_values("recorded_at")
    prev: dict[str, str] = {}
    for r in df.to_dict("records"):
        comp, h = str(r["component"]), str(r["version_hash"])
        before = prev.get(comp)
        prev[comp] = h
        out.append(
            _ev(
                "config_changed",
                r["recorded_at"],
                f"{comp} {'changed' if before else 'recorded'}: {h[:8]}",
                f"{comp}:{h}",
                detail=f"was {before[:8]}" if before else (text(r.get("reason")) or None),
                actor=text(r.get("recorded_by")),
                tone="neutral",
                href="/settings",
            )
        )
    return out


def _report_events() -> list[dict]:
    out = []
    for m in reports.list_meta():
        verdict = f" ({m['verdict']})" if m["verdict"] else ""
        out.append(
            _ev(
                "report",
                pd.Timestamp(m["created_at"]) if m["created_at"] else None,
                f"{AUTHOR_LABELS.get(m['author'], m['author'].capitalize())} report{verdict}: {m['title']}",
                m["report_id"],
                definition_version=m["definition_version"] or None,
                actor=m["author"],
                tone="warn" if m["verdict"] in ("concern", "block", "fail") else "neutral",
                href=f"/agents/reports/{m['report_id']}",
            )
        )
    return out


def _benchmark_events() -> list[dict]:
    st = deps.ui_store()
    df = read_table(
        st,
        "ops",
        "improvement_ledger",
        columns=["computed_at", "run_id", "verdict_code", "title", "active_definition"],
        ts=["computed_at"],
    )
    tone = {"improved": "good", "regressed": "crit", "not_best": "warn", "no_change": "neutral"}
    return [
        _ev(
            "benchmark",
            r["computed_at"],
            f"Evidence recomputed: {text(r.get('title')) or r.get('verdict_code')}",
            str(r["run_id"]),
            definition_version=text(r.get("active_definition")),
            actor="harness",
            tone=tone.get(str(r.get("verdict_code")), "neutral"),
            href="/progress",
        )
        for r in (df.to_dict("records") if len(df) else [])
    ]


@ttl_cache(10)
def all_events() -> list[dict]:
    builders = [
        _definition_events,
        _data_events,
        _stage_events,
        _cycle_events,
        _evaluation_events,
        _gate_events,
        _approval_events,
        _promotion_events,
        _alert_events,
        _config_events,
        _report_events,
        _benchmark_events,
    ]
    out: list[dict] = []
    for b in builders:
        out.extend(e for e in b() if e is not None)
    out.sort(key=lambda e: (e["_ts"], e["id"]), reverse=True)
    seen: dict[str, int] = {}
    for e in out:  # ids are the pagination cursor's tie-breaker, so they must be unique
        n = seen.get(e["id"], 0)
        seen[e["id"]] = n + 1
        if n:
            e["id"] = f"{e['id']}#{n + 1}"
    return out


CURSOR_SEP = "~"


def cursor_of(e: dict) -> str:
    """Opaque pagination cursor: the event's timestamp and id (events sort by both, newest first)."""
    return f"{e['ts']}{CURSOR_SEP}{e['id']}"


def parse_cursor(before: str | None) -> tuple[pd.Timestamp, str | None] | None:
    """A cursor from `cursor_of`, or a bare ISO timestamp (then strictly older than that instant)."""
    from lau.console.util import parse_ts

    if not before:
        return None
    ts_text, _, ident = before.partition(CURSOR_SEP)
    ts = parse_ts(ts_text)
    return None if ts is None else (ts, ident or None)


def public(e: dict) -> dict:
    return {k: v for k, v in e.items() if not k.startswith("_")}


def page(
    types: list[str] | None = None,
    definition: str | None = None,
    before: str | None = None,
    limit: int = 100,
    exclude_quiet: bool = False,
) -> dict:
    items = all_events()
    if types:
        items = [e for e in items if e["type"] in types]
    elif exclude_quiet:
        items = [e for e in items if e["type"] not in QUIET_TYPES]
    if definition:
        items = [e for e in items if e.get("definition_version") in (None, definition)]
    cursor = parse_cursor(before)
    if cursor is not None:
        ts, ident = cursor
        if ident is None:
            items = [e for e in items if e["_ts"] < ts]
        else:  # strictly after the cursor in (timestamp, id) descending order: ties at the boundary are kept
            items = [e for e in items if e["_ts"] < ts or (e["_ts"] == ts and e["id"] < ident)]
    chunk = items[: max(1, min(limit, 500))]
    more = len(items) > len(chunk)
    return {"events": [public(e) for e in chunk], "next_before": cursor_of(chunk[-1]) if more and chunk else None}


def between(start: pd.Timestamp, end: pd.Timestamp, limit: int = 300) -> list[dict]:
    lo, hi = min(start, end), max(start, end)
    return [public(e) for e in all_events() if lo < e["_ts"] <= hi][:limit]
