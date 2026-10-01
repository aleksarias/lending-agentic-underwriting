"""Operational state the console shows: cycles, agent trace, heartbeats, pipeline freshness, queue, jobs, cost,
alerts, monitoring, shadow scoring, config versions and access checks. All reads go through the read-only ui store.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

import pandas as pd
import yaml

from lau.console import deps
from lau.console.services import config
from lau.console.services import definitions as defs
from lau.console.util import (
    boolean,
    col,
    integer,
    iso,
    loads,
    now_utc,
    num,
    query,
    read_table,
    sql_str,
    table_exists,
    text,
    ttl_cache,
)
from lau.settings import ROOT, get_settings

# Agent roles in the order a cycle runs them.
AGENT_ROLES = ["planner", "profiler", "feature", "modeling", "redteam", "compliance", "curator"]
# Tool calls whose result is computed by the harness or a deterministic tool (a measurement, not an agent claim).
MEASURED_ACTIONS = {"train_candidate", "evaluate_candidate"}
SYSTEM_ACTIONS = {"agent_run", "denied_tool", "cycle_start", "cycle_end"}


# ---------------------------------------------------------------------------------------------------------- cycles
@ttl_cache(5)
def cycles() -> pd.DataFrame:
    """ops.cycles, newest first."""
    df = read_table(deps.ui_store(), "ops", "cycles", ts=["started_at"])
    return df.sort_values("started_at", ascending=False).reset_index(drop=True) if len(df) else df


def _stale_after_s() -> float:
    """A 'running' cycle with no heartbeat for longer than its wall-clock cap (+10 min) was abandoned."""
    return (float(config.cycle_caps().get("max_wall_clock_min", 60)) + 10) * 60


def cycle_status(r: dict, last_beat: pd.Timestamp | None = None) -> str:
    s = loads(r.get("summary_json"), {}) or {}
    status = text(r.get("status")) or text(s.get("status")) or "unknown"
    if status == "running":
        ref = last_beat if last_beat is not None else r.get("started_at")
        if ref is not None and not pd.isna(ref) and (now_utc() - pd.Timestamp(ref)).total_seconds() > _stale_after_s():
            return "abandoned"
    return status


def cycle_summary(r: dict) -> dict:
    s = loads(r.get("summary_json"), {}) or {}
    beat = last_heartbeat(str(r["cycle_id"]))
    return {
        "cycle_id": str(r["cycle_id"]),
        "definition_version": str(text(r.get("definition_version")) or ""),
        "reason": str(text(r.get("reason")) or ""),
        "status": cycle_status(r, None if beat is None else beat["ts"]),
        "started_at": iso(r["started_at"]),
        "anthropic_usd": num(s.get("anthropic_usd")),
        "challenger": text(s.get("challenger")),
        "challenger_passed_validation": boolean(s.get("challenger_passed_validation")),
        "redteam_verdict": text(s.get("redteam_verdict")),
        "compliance_verdict": text(s.get("compliance_verdict")),
        "experiments_used": integer(s.get("experiments_used")),
        "stop_reason": text(s.get("stop_reason")),
    }


def cycle_row(cycle_id: str) -> dict | None:
    df = cycles()
    if df.empty:
        return None
    hit = df[df["cycle_id"] == cycle_id]
    return None if hit.empty else hit.iloc[0].to_dict()


def running_cycle() -> dict | None:
    """The newest cycle that is still running (and not abandoned), or None."""
    df = cycles()
    if df.empty:
        return None
    for r in df[df["status"] == "running"].to_dict("records"):
        beat = last_heartbeat(str(r["cycle_id"]))
        if cycle_status(r, None if beat is None else beat["ts"]) == "running":
            return r
    return None


def cycle_finished_at(cycle_id: str) -> pd.Timestamp | None:
    """When a cycle ended: its 'end' heartbeat, else its last trace entry."""
    hb = heartbeats(cycle_id)
    if len(hb):
        end = hb[hb["step"] == "end"]
        if len(end):
            return end["ts"].max()
    tr = trace_frame(cycle_id)
    return tr["ts"].max() if len(tr) else None


# ------------------------------------------------------------------------------------------------------ heartbeats
@ttl_cache(5)
def heartbeats(cycle_id: str) -> pd.DataFrame:
    df = read_table(
        deps.ui_store(), "ops", "cycle_heartbeat", where=f"cycle_id = {sql_str(cycle_id)}", order_by="ts", ts=["ts"]
    )
    return df


def last_heartbeat(cycle_id: str) -> dict | None:
    df = heartbeats(cycle_id)
    return None if df.empty else df.iloc[-1].to_dict()


@ttl_cache(5)
def stop_requests(cycle_id: str) -> pd.DataFrame:
    return read_table(
        deps.ui_store(), "ops", "cycle_control", where=f"cycle_id = {sql_str(cycle_id)}", order_by="ts", ts=["ts"]
    )


# ----------------------------------------------------------------------------------------------------------- trace
@ttl_cache(5)
def trace_frame(cycle_id: str) -> pd.DataFrame:
    return read_table(
        deps.ui_store(), "ops", "agent_trace", where=f"cycle_id = {sql_str(cycle_id)}", order_by="ts", ts=["ts"]
    )


def trace_kind(agent: str, action: str, state_changing: bool) -> str:
    if action in SYSTEM_ACTIONS or agent in ("orchestrator", "system"):
        return "system"
    if action in MEASURED_ACTIONS or not state_changing:
        return "measured"
    return "proposed"


def _short_json(v, limit: int = 90) -> str:
    if v in (None, "", {}, []):
        return ""
    s = v if isinstance(v, str) else json.dumps(v, default=str, separators=(",", ":"))
    return s if len(s) <= limit else s[: limit - 1] + "…"


def trace_summary(agent: str, action: str, status: str, inputs: dict | str | None, outputs: dict | str | None) -> str:
    """One line: tool + key inputs + outcome."""
    if action == "agent_run" and isinstance(outputs, dict):
        calls = outputs.get("tool_calls") or []
        return (
            f"{agent} run ended ({outputs.get('subtype', status)}): {outputs.get('turns', 0)} turns, "
            f"{len(calls)} tool calls"
        )
    if action == "denied_tool" and isinstance(inputs, dict):
        return f"denied: {inputs.get('tool')} is not permitted for the {agent} agent"
    args = inputs if isinstance(inputs, dict) else {}
    key_args = {k: v for k, v in args.items() if k not in ("body", "markdown", "text", "sql")}
    head = f"{action}({_short_json(key_args, 70)})" if key_args else action
    if "sql" in args:
        head = f"{action}: {_short_json(str(args['sql']).strip(), 90)}"
    if status not in ("ok", "success"):
        err = outputs.get("error") if isinstance(outputs, dict) else outputs
        return f"{head} → {status}: {_short_json(err, 100)}"
    if isinstance(outputs, dict):
        for k in ("model_version", "passed_validation", "val_auc", "feature_id", "report_id", "n_rows", "recorded"):
            if k in outputs:
                return f"{head} → {k}={_short_json(outputs[k], 40)}"
    return head


def trace_entry(r: dict, idx: int) -> dict:
    agent, action = str(r.get("agent") or ""), str(r.get("action") or "")
    status = str(r.get("status") or "ok")
    state_changing = bool(boolean(r.get("state_changing")))
    inputs, outputs = loads(r.get("inputs"), r.get("inputs")), loads(r.get("outputs"), r.get("outputs"))
    ts = pd.Timestamp(r["ts"])
    ident = hashlib.sha256(f"{r.get('cycle_id')}|{ts.value}|{agent}|{action}|{idx}".encode()).hexdigest()[:12]
    raw_in, raw_out = text(r.get("inputs")), text(r.get("outputs"))
    return {
        "id": ident,
        "ts": iso(ts),
        "cycle_id": str(r.get("cycle_id") or ""),
        "agent": agent,
        "action": action,
        "status": status,
        "state_changing": state_changing,
        "summary": trace_summary(agent, action, status, inputs, outputs),
        "kind": trace_kind(agent, action, state_changing),
        "cost_usd": num(r.get("cost_usd")) or 0.0,
        "inputs": None if raw_in is None else raw_in[:4000],
        "outputs": None if raw_out is None else raw_out[:4000],
    }


def trace_entries(cycle_id: str, after: str | None = None, limit: int = 500) -> list[dict]:
    df = trace_frame(cycle_id)
    if df.empty:
        return []
    out = [trace_entry(r, i) for i, r in enumerate(df.to_dict("records"))]
    if after:
        cut = pd.Timestamp(after)
        cut = cut.tz_localize("UTC") if cut.tzinfo is None else cut
        out = [e for e in out if pd.Timestamp(e["ts"]) > cut]
    return out[-limit:]


def agent_runs(cycle_id: str | None = None) -> pd.DataFrame:
    """agent_run trace rows (one per specialist run) with parsed outputs."""
    st = deps.ui_store()
    where = "action = 'agent_run'" + (f" AND cycle_id = {sql_str(cycle_id)}" if cycle_id else "")
    df = read_table(
        st,
        "ops",
        "agent_trace",
        where=where,
        order_by="ts",
        columns=["ts", "cycle_id", "agent", "status", "cost_usd", "outputs"],
        ts=["ts"],
    )
    if df.empty:
        return df
    outs = [loads(x, {}) or {} for x in col(df, "outputs")]
    df["subtype"] = [str(o.get("subtype") or s) for o, s in zip(outs, df["status"], strict=True)]
    df["turns"] = [integer(o.get("turns")) or 0 for o in outs]
    df["tool_calls"] = [len(o.get("tool_calls") or []) for o in outs]
    return df.drop(columns=["outputs"])


def cycle_steps(cycle_id: str, started_at) -> list[dict]:
    """Per agent run: role, outcome, turns, cost, tool calls and duration (since the previous run ended)."""
    runs = agent_runs(cycle_id)
    # the trace flush after each run can duplicate a run with status "success" and zero cost: keep the costed one
    if runs.empty:
        return []
    runs = runs.sort_values(["ts", "cost_usd"]).reset_index(drop=True)
    steps, prev = [], pd.Timestamp(started_at) if started_at is not None else None
    seen: set[tuple[str, int]] = set()
    for r in runs.to_dict("records"):
        key = (r["agent"], int(r["turns"]))
        if key in seen and not num(r["cost_usd"]):
            continue
        seen.add(key)
        ts = pd.Timestamp(r["ts"])
        steps.append(
            {
                "role": str(r["agent"]),
                "subtype": str(r["subtype"]),
                "turns": int(r["turns"]),
                "cost_usd": num(r["cost_usd"]) or 0.0,
                "tool_calls": int(r["tool_calls"]),
                "duration_s": max(0.0, (ts - prev).total_seconds()) if prev is not None else 0.0,
            }
        )
        prev = ts
    return steps


def cycle_plan(cycle_id: str) -> dict | None:
    """The plan the planner submitted for a cycle (its submit_plan tool input)."""
    df = read_table(
        deps.ui_store(),
        "ops",
        "agent_trace",
        where=f"cycle_id = {sql_str(cycle_id)} AND action = 'submit_plan'",
        columns=["ts", "inputs"],
        order_by="ts DESC",
        limit=1,
    )
    if df.empty:
        return None
    plan = loads(df["inputs"].iloc[0], None)
    return plan if isinstance(plan, dict) else None


def latest_plan() -> tuple[str | None, dict | None]:
    df = read_table(
        deps.ui_store(),
        "ops",
        "agent_trace",
        where="action = 'submit_plan'",
        columns=["ts", "cycle_id", "inputs"],
        order_by="ts DESC",
        limit=1,
    )
    if df.empty:
        return None, None
    plan = loads(df["inputs"].iloc[0], None)
    return str(df["cycle_id"].iloc[0]), plan if isinstance(plan, dict) else None


def cycle_report_markdown(cycle_id: str) -> str | None:
    p = get_settings().reports_dir / cycle_id / "cycle_report.md"
    try:
        return p.read_text()[:200_000] if p.is_file() else None
    except OSError:
        return None


def lanes(cycle_id: str) -> list[dict]:
    """One lane per agent role for a live cycle, from heartbeats (state) and agent_run rows (turns, cost)."""
    hb = heartbeats(cycle_id)
    runs = agent_runs(cycle_id)
    out = []
    for role in AGENT_ROLES:
        caps = config.agent_caps(role)
        mine = hb[hb["agent"] == role] if len(hb) and "agent" in hb.columns else pd.DataFrame()
        state, started, finished = "pending", None, None
        if len(mine):
            last = mine.iloc[-1]
            state = {"running": "running", "done": "done", "error": "error"}.get(str(last["state"]), "pending")
            started = iso(mine[mine["state"] == "running"]["ts"].min()) if (mine["state"] == "running").any() else None
            finished = iso(last["ts"]) if state in ("done", "error") else None
        r = runs[runs["agent"] == role] if len(runs) else pd.DataFrame()
        out.append(
            {
                "role": role,
                "state": state,
                "turns": int(r["turns"].sum()) if len(r) else 0,
                "max_turns": caps["max_turns"],
                "cost_usd": float(r["cost_usd"].fillna(0).sum()) if len(r) else 0.0,
                "max_cost_usd": caps["max_budget_usd"],
                "started_at": started,
                "finished_at": finished,
            }
        )
    return out


def gauges(cycle_id: str, started_at) -> list[dict]:
    caps = config.cycle_caps()
    beat = last_heartbeat(cycle_id) or {}
    elapsed = (now_utc() - pd.Timestamp(started_at)).total_seconds() / 60 if started_at is not None else 0.0
    return [
        {
            "key": "experiments",
            "label": "Validation tests",
            "used": float(integer(beat.get("experiments_used")) or 0),
            "cap": float(caps.get("max_experiments", 0)),
            "unit": "tests",
        },
        {
            "key": "anthropic_usd",
            "label": "Agent spend",
            "used": float(num(beat.get("spent_usd")) or 0.0),
            "cap": float(caps.get("max_anthropic_usd", 0)),
            "unit": "USD",
        },
        {
            "key": "wall_clock",
            "label": "Wall clock",
            "used": round(max(0.0, elapsed), 1),
            "cap": float(caps.get("max_wall_clock_min", 0)),
            "unit": "min",
        },
    ]


# -------------------------------------------------------------------------------------------------------- pipeline
@lru_cache(maxsize=1)
def stage_catalog() -> tuple[tuple[str, bool, str], ...]:
    """(name, definition_dependent, description) for every pipeline stage in DAG order (no data access)."""
    from lau.pipeline.stages import build_pipeline

    pipe = build_pipeline()
    return tuple((n, bool(pipe.stages[n].definition_dependent), pipe.stages[n].description) for n in pipe.order)


@ttl_cache(10)
def pipeline_rows() -> pd.DataFrame:
    return read_table(deps.ui_store(), "ops", "pipeline_state", ts=["started_at", "finished_at"])


def _duration(r: dict) -> float | None:
    a, b = r.get("started_at"), r.get("finished_at")
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return None
    return max(0.0, (pd.Timestamp(b) - pd.Timestamp(a)).total_seconds())


def freshness(version: str | None) -> list[dict]:
    """StageFreshness per stage for a definition version (latest recorded run of each stage)."""
    rows = pipeline_rows()
    active = defs.active_version()
    yaml_v = config.yaml_definition_version()
    out = []
    for name, dependent, _desc in stage_catalog():
        sub = rows[rows["stage"] == name] if len(rows) else rows
        if dependent and len(sub):
            sub = sub[sub["definition_version"] == version]
        latest = sub.sort_values("started_at").iloc[-1].to_dict() if len(sub) else None
        reason = None
        if latest is None:
            status, reason = "never", "not built for this definition yet"
        elif str(latest.get("status")) == "failed":
            status = "failed"
            reason = text((loads(latest.get("details"), {}) or {}).get("error")) or "the last run failed"
        elif str(latest.get("status")) == "running":
            status, reason = "stale", "rebuilding now"
        else:
            status = "fresh"
        if status == "fresh" and dependent and version == active and yaml_v and active and yaml_v != active:
            status, reason = "stale", "config/default_definition.yaml differs from the active definition"
        out.append(
            {
                "stage": name,
                "status": status,
                "last_run_at": iso(latest.get("finished_at") or latest.get("started_at")) if latest else None,
                "duration_s": _duration(latest) if latest else None,
                "definition_version": text(latest.get("definition_version")) if latest else None,
                "reason": reason,
            }
        )
    return out


def pipeline_running() -> dict | None:
    rows = pipeline_rows()
    if rows.empty:
        return None
    run = rows[rows["status"] == "running"]
    if run.empty:
        return None
    r = run.sort_values("started_at").iloc[-1]
    if (now_utc() - pd.Timestamp(r["started_at"])).total_seconds() > 6 * 3600:
        return None
    return {"stage": str(r["stage"]), "since": iso(r["started_at"])}


def pipeline_runs(version: str | None, limit: int = 200) -> list[dict]:
    rows = pipeline_rows()
    if rows.empty:
        return []
    if version:
        rows = rows[rows["definition_version"] == version]
    rows = rows.sort_values("started_at", ascending=False).head(limit)
    return [
        {
            "stage": str(r["stage"]),
            "definition_version": str(r["definition_version"]),
            "status": str(r["status"]),
            "started_at": iso(r["started_at"]),
            "finished_at": iso(r.get("finished_at")),
            "duration_s": _duration(r) or 0.0,
        }
        for r in rows.to_dict("records")
    ]


# ------------------------------------------------------------------------------------------------ queue and counter
@ttl_cache(10)
def queue() -> list[dict]:
    df = read_table(deps.ui_store(), "ops", "cycle_queue", ts=["requested_at"])
    if df.empty:
        return []
    df = df.sort_values("requested_at", ascending=False)
    return [
        {
            "requested_at": iso(r["requested_at"]),
            "definition_version": str(r["definition_version"]),
            "reason": str(text(r.get("reason")) or ""),
            "status": str(text(r.get("status")) or ""),
        }
        for r in df.to_dict("records")
    ]


@ttl_cache(30)
def declared_jobs() -> list[dict]:
    """Scheduled jobs as declared in the Databricks Asset Bundle (resources/jobs.yml); every target deploys them
    paused. The console does not call the Jobs API (its read-only identity has no job permissions)."""
    try:
        doc = yaml.safe_load((ROOT / "resources" / "jobs.yml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    out = []
    for key, job in ((doc.get("resources") or {}).get("jobs") or {}).items():
        periodic = ((job or {}).get("trigger") or {}).get("periodic") or {}
        schedule = None
        if periodic:
            n, unit = int(periodic.get("interval", 1)), str(periodic.get("unit", "")).lower()
            schedule = {("days", 1): "Daily", ("weeks", 1): "Weekly", ("hours", 1): "Hourly"}.get(
                (unit, n), f"Every {n} {unit}"
            )
        out.append(
            {
                "name": str(job.get("name") or key),
                "paused": True,
                "schedule": schedule,
                "next_run_at": None,
                "last_result": None,
                "last_run_at": None,
            }
        )
    return out


# ------------------------------------------------------------------------------------------------------------ cost
@ttl_cache(15)
def cost_log() -> pd.DataFrame:
    return read_table(deps.ui_store(), "ops", "cost_log", ts=["ts"])


def month_to_date_usd() -> float:
    df = cost_log()
    if df.empty:
        return 0.0
    now = now_utc()
    mine = df[(df["ts"].dt.year == now.year) & (df["ts"].dt.month == now.month)]
    return float(mine["usd"].fillna(0).sum())


def hard_stop_usd() -> float:
    return float(config.budgets().get("monthly", {}).get("hard_stop_usd", 0.0))


def cycle_cost_usd(cycle_id: str | None) -> float | None:
    df = cost_log()
    if df.empty or not cycle_id:
        return None
    mine = df[df["cycle_id"] == cycle_id]
    return float(mine["usd"].fillna(0).sum()) if len(mine) else None


# ------------------------------------------------------------------------------------------ alerts and monitoring
def alert_id(ts, kind: str, subject: str) -> str:
    """Contract: first 12 hex of sha256("{ts.isoformat()}|{kind}|{subject}") with ts as UTC."""
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return hashlib.sha256(f"{t.isoformat()}|{kind}|{subject}".encode()).hexdigest()[:12]


@ttl_cache(10)
def monitoring_runs() -> list[dict]:
    df = read_table(deps.ui_store(), "ops", "monitoring_runs", ts=["ts"])
    out = []
    for r in df.sort_values("ts", ascending=False).to_dict("records") if len(df) else []:
        s = loads(r.get("summary_json"), {}) or {}
        out.append(
            {
                "ts": iso(r["ts"]),
                "definition_version": str(r.get("definition_version") or ""),
                "score_psi": num(s.get("score_psi")),
                "max_feature_psi": num(s.get("max_feature_psi")),
                "alerts": len(s.get("alerts") or []),
                "summary": s,
            }
        )
    return out


@ttl_cache(10)
def acks() -> dict[str, dict]:
    df = read_table(deps.ui_store(), "ops", "alert_acks", ts=["acked_at"])
    out: dict[str, dict] = {}
    for r in df.sort_values("acked_at").to_dict("records") if len(df) else []:
        out[str(r["alert_id"])] = {"by": text(r.get("acked_by")), "at": iso(r["acked_at"]), "note": text(r.get("note"))}
    return out


@ttl_cache(10)
def alerts() -> list[dict]:
    """Every alert, newest first, with acknowledgement and whether it is current (raised by the latest run)."""
    df = read_table(deps.ui_store(), "ops", "alerts", ts=["ts"])
    if df.empty:
        return []
    runs = monitoring_runs()
    latest = pd.Timestamp(runs[0]["ts"]) if runs else df["ts"].max()
    ack = acks()
    out = []
    for r in df.sort_values("ts", ascending=False).to_dict("records"):
        aid = alert_id(r["ts"], str(r["kind"]), str(r["subject"]))
        sev = str(r.get("severity") or "low")
        out.append(
            {
                "id": aid,
                "ts": iso(r["ts"]),
                "kind": str(r["kind"]),
                "subject": str(r["subject"]),
                "value": num(r.get("value")) or 0.0,
                "severity": sev if sev in ("high", "medium", "low") else "low",
                "definition_version": str(r.get("definition_version") or ""),
                "acknowledged": aid in ack,
                "ack_by": (ack.get(aid) or {}).get("by"),
                "ack_at": (ack.get(aid) or {}).get("at"),
                "ack_note": (ack.get(aid) or {}).get("note"),
                "title": alert_title(str(r["kind"]), str(r["subject"]), num(r.get("value")) or 0.0),
                "current": abs((pd.Timestamp(r["ts"]) - latest).total_seconds()) < 2,
            }
        )
    return out


def alert_title(kind: str, subject: str, value: float) -> str:
    """Plain-language alert headline, e.g. "Score distribution shifted (PSI 0.302)"."""
    what = "Score" if subject == "score" else subject.replace("_", " ")
    what = what[:1].upper() + what[1:]
    if kind == "psi":
        return f"{what} distribution shifted (PSI {value:.3f})"
    if kind == "default_rate":
        return f"Observed default rate {value:+.0%} versus expected"
    return f"{kind.replace('_', ' ').capitalize()}: {what} ({value:.3f})"


def open_alerts() -> dict[str, int]:
    """Unacknowledged alerts raised by the latest monitoring run, by severity."""
    counts = {"high": 0, "medium": 0}
    for a in alerts():
        if a["current"] and not a["acknowledged"] and a["severity"] in counts:
            counts[a["severity"]] += 1
    return counts


# --------------------------------------------------------------------------------------------------------- shadow
@ttl_cache(30)
def shadow() -> dict:
    """Aggregates over ops.shadow_scores (never row-level scores)."""
    st = deps.ui_store()
    if not table_exists(st, "ops", "shadow_scores"):
        return {
            "available": False,
            "reason": "Shadow scoring has not run yet (lau shadow, or the lau-shadow-scoring job).",
            "runs": [],
            "distributions": [],
            "agreement_at_policy": None,
        }
    t = st.fq("ops", "shadow_scores")
    runs = query(
        st,
        f"SELECT scored_at, definition_version, role, model_version, count(*) AS n, avg(pd) AS mean_pd FROM {t} "
        "GROUP BY scored_at, definition_version, role, model_version ORDER BY scored_at DESC LIMIT 200",
        ts=["scored_at"],
    )
    latest_where = f"scored_at = (SELECT max(scored_at) FROM {t})"
    hist = query(
        st,
        f"SELECT role, least(floor(pd * 20), 19) AS b, count(*) AS n FROM {t} WHERE {latest_where} "
        "GROUP BY role, least(floor(pd * 20), 19)",
    )
    distributions = []
    for role, g in hist.groupby("role") if len(hist) else []:
        total = float(g["n"].sum())
        shares = {int(b): float(n) / total for b, n in zip(g["b"], g["n"], strict=True)}
        distributions.append(
            {"role": str(role), "bins": [{"edge": i / 20, "share": shares.get(i, 0.0)} for i in range(20)]}
        )
    agreement = None
    roles = set(hist["role"]) if len(hist) else set()
    if {"serving", "challenger"} <= roles:
        rate = config.fixed_approval_rate()
        try:
            a = query(
                st,
                f"WITH s AS (SELECT application_id, role, pd FROM {t} WHERE {latest_where} "
                "AND role IN ('serving', 'challenger')), "
                f"q AS (SELECT role, percentile_cont({rate}) WITHIN GROUP (ORDER BY pd) AS cut FROM s GROUP BY role), "
                "d AS (SELECT s.application_id, s.role, CASE WHEN s.pd <= q.cut THEN 1 ELSE 0 END AS approve "
                "FROM s JOIN q ON s.role = q.role) "
                "SELECT avg(CASE WHEN a.approve = b.approve THEN 1.0 ELSE 0.0 END) AS agree FROM d a JOIN d b "
                "ON a.application_id = b.application_id AND a.role = 'serving' AND b.role = 'challenger'",
            )
            agreement = num(a["agree"].iloc[0]) if len(a) else None
        except Exception:  # noqa: BLE001 - an optional statistic
            agreement = None
    return {
        "available": True,
        "reason": None,
        "runs": [
            {
                "scored_at": iso(r["scored_at"]),
                "definition_version": str(r["definition_version"]),
                "role": str(r["role"]),
                "model_version": str(r["model_version"]),
                "n": integer(r["n"]) or 0,
                "mean_pd": num(r["mean_pd"]) or 0.0,
            }
            for r in runs.to_dict("records")
        ],
        "distributions": distributions,
        "agreement_at_policy": agreement,
    }


# -------------------------------------------------------------------------------------- config versions and access
@ttl_cache(30)
def config_versions() -> pd.DataFrame:
    return read_table(
        deps.ui_store(),
        "ops",
        "config_versions",
        columns=["recorded_at", "component", "version_hash", "git_sha", "recorded_by", "reason"],
        ts=["recorded_at"],
    )


def config_versions_latest() -> list[dict]:
    df = config_versions()
    if df.empty:
        return []
    latest = df.sort_values("recorded_at").groupby("component").tail(1).sort_values("component")
    return [
        {
            "component": str(r["component"]),
            "version": str(r["version_hash"]),
            "recorded_at": iso(r["recorded_at"]),
            "git_sha": text(r.get("git_sha")),
        }
        for r in latest.to_dict("records")
    ]


def config_vector_at(ts: pd.Timestamp) -> dict[str, str]:
    """{component: version_hash} in effect at `ts` (the latest record at or before it)."""
    df = config_versions()
    if df.empty:
        return {}
    df = df[df["recorded_at"] <= ts]
    if df.empty:
        return {}
    latest = df.sort_values("recorded_at").groupby("component").tail(1)
    return {str(c): str(v) for c, v in zip(latest["component"], latest["version_hash"], strict=True)}


@ttl_cache(30)
def access_checks() -> list[dict]:
    df = read_table(deps.ui_store(), "ops", "access_checks", ts=["checked_at"])
    if df.empty:
        return []
    last = df["checked_at"].max()
    df = df[(df["checked_at"] - last).abs() <= pd.Timedelta(minutes=10)]
    return [
        {
            "role": str(r["role"]),
            "object": str(r["object"]),
            "expected": "allow" if str(r["expected"]) == "allow" else "deny",
            "observed": str(r.get("observed") or ""),
            "ok": bool(boolean(r.get("ok"))),
            "checked_at": iso(r["checked_at"]),
        }
        for r in df.sort_values(["role", "object"]).to_dict("records")
    ]


# ------------------------------------------------------------------------------------------------- data versions
@ttl_cache(30)
def data_versions() -> pd.DataFrame:
    df = read_table(
        deps.ui_store(),
        "ops",
        "data_version",
        columns=["data_version", "created_at", "as_of_month", "n_applications"],
        ts=["created_at"],
    )
    return df.sort_values("created_at").reset_index(drop=True) if len(df) else df


def latest_data_version() -> dict | None:
    df = data_versions()
    return None if df.empty else df.iloc[-1].to_dict()


def data_version_at(ts: pd.Timestamp) -> dict | None:
    df = data_versions()
    if df.empty:
        return None
    df = df[df["created_at"] <= ts]
    return None if df.empty else df.iloc[-1].to_dict()
