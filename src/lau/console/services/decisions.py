"""Decisions, the decision API's state, the active policy and rollouts, as the console shows them.

Reads only what the ui identity may read: ops.decisions (no applicant inputs), ops.decision_builds,
ops.release_checks, ops.active_policy / ops.policy_versions, production.rollouts, ops.rollout_approvals, and the
endpoint state the snapshot publishes (extras/decision_api.json). Test traffic (load and parity checks) is excluded
from every figure.
"""

from __future__ import annotations

import json

from lau.console import deps
from lau.console.util import boolean, integer, iso, loads, num, query, sql_str, table_exists, text, ttl_cache
from lau.settings import get_settings

WINDOW_DAYS = 30
RECENT = 50
ROW_COLUMNS = (
    "decision_id, application_id, decided_at, decision_date, decision, path, probability_of_default, risk_band, "
    "reason_codes, model_version, definition_version, policy_version, build_id, fallback_used, fallback_reason, "
    "reasons_missing, latency_ms, client_latency_ms, shadow_model_version, shadow_decision, "
    "shadow_probability_of_default, source"
)


def _table(st) -> str:
    return st.fq("ops", "decisions")


def _row(r: dict) -> dict:
    return {
        "decision_id": str(r["decision_id"]),
        "application_id": str(r["application_id"]),
        "decided_at": iso(r.get("decided_at")),
        "decision_date": text(r.get("decision_date")),
        "decision": str(r["decision"]),
        "path": str(r["path"]),
        "probability_of_default": num(r.get("probability_of_default")),
        "risk_band": text(r.get("risk_band")),
        "reason_codes": [c for c in (text(r.get("reason_codes")) or "").split(",") if c],
        "model_version": text(r.get("model_version")),
        "policy_version": text(r.get("policy_version")),
        "fallback_used": bool(boolean(r.get("fallback_used"))),
        "latency_ms": num(r.get("latency_ms")),
        "shadow_decision": text(r.get("shadow_decision")),
    }


# ---- policy ---------------------------------------------------------------------------------------------------------
@ttl_cache(15)
def policy_info() -> dict | None:
    st = deps.ui_store()
    if not (table_exists(st, "ops", "active_policy") and table_exists(st, "ops", "policy_versions")):
        return None
    df = query(
        st,
        f"SELECT a.policy_version, a.activated_at, a.activated_by, v.name, v.policy_json "
        f"FROM {st.fq('ops', 'active_policy')} a JOIN {st.fq('ops', 'policy_versions')} v "
        "ON a.policy_version = v.policy_version ORDER BY a.activated_at DESC LIMIT 1",
        ts=["activated_at"],
    )
    if df.empty:
        return None
    r = df.iloc[0].to_dict()
    p = loads(r["policy_json"], {}) or {}
    approvers = []
    if table_exists(st, "ops", "policy_approvals"):
        a = query(
            st,
            f"SELECT approved_by FROM {st.fq('ops', 'policy_approvals')} "
            f"WHERE policy_version = {sql_str(str(r['policy_version']))} ORDER BY approved_at",
        )
        approvers = list(dict.fromkeys(str(x) for x in a["approved_by"])) if len(a) else []
    knock = p.get("knockouts") or {}
    return {
        "version": str(r["policy_version"]),
        "name": text(r.get("name")) or "",
        "activated_at": iso(r.get("activated_at")),
        "activated_by": text(r.get("activated_by")),
        "approve_max_pd": num((p.get("decision") or {}).get("approve_max_pd")),
        "refer_max_pd": num((p.get("decision") or {}).get("refer_max_pd")),
        "knockouts": {"max_dti": num(knock.get("max_dti")), "min_bureau_score": num(knock.get("min_bureau_score"))},
        "bands": [{"band": str(k), "max_pd": float(v)} for k, v in (p.get("bands") or {}).items()],
        "reason_codes": integer(p.get("reason_codes")),
        "legacy_min_score": num((p.get("legacy") or {}).get("min_score")),
        "approvers": approvers,
    }


# ---- the decision API ----------------------------------------------------------------------------------------------
def _endpoint() -> dict:
    from lau.console.snapshot import mirror_extra

    name = get_settings().decisioning["endpoint"]["name"]
    raw = mirror_extra("decision_api.json")
    if raw is None:
        return {"name": name, "exists": False, "known": False, "reason": "endpoint state is published by the snapshot"}
    info = loads(raw.decode(), {}) or {}
    return {"known": True, **info, "name": info.get("name") or name}


@ttl_cache(15)
def latest_build() -> dict | None:
    st = deps.ui_store()
    if not table_exists(st, "ops", "decision_builds"):
        return None
    df = query(st, f"SELECT * FROM {st.fq('ops', 'decision_builds')} ORDER BY built_at DESC LIMIT 1", ts=["built_at"])
    if df.empty:
        return None
    r = df.iloc[0].to_dict()
    return {
        "version": str(r["decision_model_version"]),
        "build_id": str(r["build_id"]),
        "built_at": iso(r.get("built_at")),
        "built_by": text(r.get("built_by")),
        "versions": loads(r.get("versions_json"), {}) or {},
    }


@ttl_cache(15)
def release_checks() -> list[dict]:
    st = deps.ui_store()
    if not table_exists(st, "ops", "release_checks"):
        return []
    df = query(st, f"SELECT * FROM {st.fq('ops', 'release_checks')} ORDER BY run_at DESC", ts=["run_at"])
    out, seen = [], set()
    for r in df.to_dict("records"):
        if r["check"] in seen:
            continue
        seen.add(r["check"])
        d = loads(r.get("details_json"), {}) or {}
        out.append(
            {
                "check": str(r["check"]),
                "passed": bool(boolean(r["passed"])),
                "run_at": iso(r["run_at"]),
                "build_id": text(r.get("build_id")),
                "summary": _check_summary(str(r["check"]), d),
                "details": d,
            }
        )
    return out


def _check_summary(check: str, d: dict) -> str:
    if check == "parity":
        return (
            f"{d.get('n')} applications; largest feature gap {d.get('max_feature_gap')}, PD gap {d.get('max_pd_gap')}"
        )
    if check == "load":
        t = d.get("targets") or {}
        p95, p99 = d.get("p95_ms"), d.get("p99_ms")
        if p95 is None:
            return f"every request failed via {d.get('transport')}"
        return (
            f"p95 {p95:.0f} ms, p99 {p99:.0f} ms (targets {t.get('p95_ms')} / {t.get('p99_ms')}) via "
            f"{d.get('transport')}; {d.get('errors')} errors; cold start {d.get('cold_start_ms')} ms"
        )
    if check == "rollback":
        seconds = d.get("seconds_to_decide_with_restored")
        basis = f" ({d['basis']})" if d.get("basis") else ""
        return f"restores {d.get('restores')}: decided {d.get('n')} applications in {seconds} s{basis}"
    return ""


def api_status() -> dict:
    from lau.console.services import models

    build = latest_build()
    policy = policy_info()
    endpoint = _endpoint()
    serving = models.serving_model()
    shadow = next((r for r in rollouts_list() if r["state"] == "shadow"), None)
    embedded = (build or {}).get("versions") or {}
    gaps = []
    if build and serving and str(embedded.get("model_version") or "") != serving["version"]:
        gaps.append(
            f"The live build decides with v{embedded.get('model_version')}, "
            f"the registry says v{serving['version']} serves."
        )
    if build and not serving and embedded.get("model_version"):
        gaps.append("The live build still embeds a model, but nothing holds the serving alias.")
    if build and policy and embedded.get("policy_version") != policy["version"]:
        gaps.append("The live build uses a policy that is no longer active.")
    if build and str(embedded.get("shadow_model_version") or "") != (shadow["model_version"] if shadow else ""):
        gaps.append("The live build's shadow model differs from the rollout in shadow.")
    if build and endpoint.get("exists") and endpoint.get("served_version") not in (None, build["version"]):
        gaps.append(
            f"The endpoint serves decision model v{endpoint.get('served_version')}, "
            f"the live build is v{build['version']}."
        )
    if policy is None:
        state = "no_policy"
    elif build is None:
        state = "not_built"
    elif endpoint.get("exists"):
        state = "endpoint" if endpoint.get("ready") else "endpoint_not_ready"
    else:
        state = "in_process"
    return {
        "state": state,
        "endpoint": endpoint,
        "live_build": build,
        "serving_model_version": serving["version"] if serving else None,
        "shadow_model_version": shadow["model_version"] if shadow else None,
        "policy_version": policy["version"] if policy else None,
        "gaps": gaps,
        "checks": release_checks(),
        "targets": get_settings().decisioning["targets"],
    }


API_LABELS = {
    "endpoint": "API live",
    "endpoint_not_ready": "API starting",
    "in_process": "Deciding in process",
    "not_built": "API not built",
    "no_policy": "No approved policy",
}


@ttl_cache(10)
def api_brief() -> dict:
    """The status bar's API chip: state, latest load-check p99, fallback share over the window."""
    a = api_status()
    load = next((c for c in a["checks"] if c["check"] == "load"), None)
    fallback = None
    if available():
        st = deps.ui_store()
        t = _table(st)
        df = query(
            st,
            "SELECT avg(CASE WHEN fallback_used THEN 1.0 ELSE 0.0 END) AS f, count(*) AS n FROM "
            f"{t} WHERE NOT is_test AND decided_at >= (SELECT max(decided_at) FROM {t}) - INTERVAL {WINDOW_DAYS} DAYS",
        )
        fallback = num(df["f"].iloc[0]) if len(df) and int(df["n"].iloc[0] or 0) else None
    return {
        "live": a["state"] in ("endpoint", "in_process") and available(),
        "state": a["state"],
        "label": API_LABELS.get(a["state"], a["state"]),
        "p99_ms": num((load or {}).get("details", {}).get("p99_ms")),
        "fallback_rate": fallback,
    }


# ---- decisions -----------------------------------------------------------------------------------------------------
def available() -> bool:
    return table_exists(deps.ui_store(), "ops", "decisions")


def overview() -> dict:
    st = deps.ui_store()
    api = api_status()
    policy = policy_info()
    base = {"window_days": WINDOW_DAYS, "policy": policy, "api": api}
    if not available():
        reason = {
            "no_policy": "No credit policy is active yet: review it with `lau policy plan`, approve it with "
            "`lau policy approve`, activate it with `lau policy apply`.",
            "not_built": "A policy is active but no decision model is built yet: `lau decision build`.",
        }.get(api["state"], "No decision has been made yet: `lau decision originate` sends synthetic applications.")
        return {
            **base,
            "available": False,
            "reason": reason,
            "as_of": None,
            "totals": None,
            "shares": None,
            "daily": [],
            "paths": [],
            "versions": [],
            "reasons": [],
            "bands": [],
            "recent": [],
            "latency": None,
        }
    t = _table(st)
    since = f"(SELECT max(decided_at) FROM {t}) - INTERVAL {WINDOW_DAYS} DAYS"
    where = f"NOT is_test AND decided_at >= {since}"
    tot = (
        query(
            st,
            "SELECT count(*) AS n, "
            "sum(CASE WHEN decision = 'approve' THEN 1 ELSE 0 END) AS approve, "
            "sum(CASE WHEN decision = 'refer' THEN 1 ELSE 0 END) AS refer, "
            "sum(CASE WHEN decision = 'decline' THEN 1 ELSE 0 END) AS decline, "
            "sum(CASE WHEN fallback_used THEN 1 ELSE 0 END) AS fallback, "
            "sum(CASE WHEN reasons_missing THEN 1 ELSE 0 END) AS reasons_missing, "
            "sum(CASE WHEN unmapped_reasons > 0 THEN 1 ELSE 0 END) AS unmapped, "
            "max(decided_at) AS as_of, "
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS model_p50, "
            "percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS model_p95 "
            f"FROM {t} WHERE {where}",
            ts=["as_of"],
        )
        .iloc[0]
        .to_dict()
    )
    n = int(tot["n"] or 0)
    totals = {
        k: int(tot[k] or 0) for k in ("n", "approve", "refer", "decline", "fallback", "reasons_missing", "unmapped")
    }
    daily = query(
        st,
        "SELECT CAST(decided_at AS DATE) AS day, count(*) AS n, "
        "sum(CASE WHEN decision = 'approve' THEN 1 ELSE 0 END) AS approve, "
        "sum(CASE WHEN decision = 'refer' THEN 1 ELSE 0 END) AS refer, "
        "sum(CASE WHEN decision = 'decline' THEN 1 ELSE 0 END) AS decline, "
        "sum(CASE WHEN fallback_used THEN 1 ELSE 0 END) AS fallback "
        f"FROM {t} WHERE {where} GROUP BY CAST(decided_at AS DATE) ORDER BY day",
    )
    paths = query(st, f"SELECT path, count(*) AS n FROM {t} WHERE {where} GROUP BY path ORDER BY n DESC")
    versions = query(
        st,
        "SELECT model_version, policy_version, build_id, count(*) AS n, min(decided_at) AS first, "
        f"max(decided_at) AS last FROM {t} WHERE {where} GROUP BY model_version, policy_version, build_id "
        "ORDER BY last DESC",
        ts=["first", "last"],
    )
    bands = query(
        st,
        "SELECT risk_band AS band, count(*) AS n, sum(CASE WHEN decision = 'approve' THEN 1 ELSE 0 END) AS approve "
        f"FROM {t} WHERE {where} AND risk_band IS NOT NULL GROUP BY risk_band ORDER BY risk_band",
    )
    declines = query(st, f"SELECT reasons_json FROM {t} WHERE {where} AND decision = 'decline'")
    counts: dict[tuple[str, str], int] = {}
    for raw in declines["reasons_json"] if len(declines) else []:
        for r in loads(raw, []) or []:
            key = (str(r.get("code")), str(r.get("statement")))
            counts[key] = counts.get(key, 0) + 1
    n_decl = max(totals["decline"], 1)
    reasons = [
        {"code": c, "statement": s, "n": k, "share": round(k / n_decl, 4)}
        for (c, s), k in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
    recent = query(
        st,
        f"SELECT {ROW_COLUMNS} FROM {t} WHERE NOT is_test ORDER BY decided_at DESC LIMIT {RECENT}",
        ts=["decided_at"],
    )
    load = next((c for c in api["checks"] if c["check"] == "load"), None)
    return {
        **base,
        "available": True,
        "reason": None,
        "as_of": iso(tot.get("as_of")),
        "totals": totals,
        "shares": {k: round(totals[k] / n, 4) if n else None for k in ("approve", "refer", "decline", "fallback")},
        "latency": {
            "model_p50_ms": num(tot.get("model_p50")),
            "model_p95_ms": num(tot.get("model_p95")),
            "load_check": load,
            "targets": get_settings().decisioning["targets"],
        },
        "daily": [
            {
                "date": str(r["day"])[:10],
                **{k: int(r[k] or 0) for k in ("n", "approve", "refer", "decline", "fallback")},
            }
            for r in daily.to_dict("records")
        ],
        "paths": [{"path": str(r["path"]), "n": int(r["n"])} for r in paths.to_dict("records")],
        "versions": [
            {
                "model_version": text(r.get("model_version")),
                "policy_version": text(r.get("policy_version")),
                "build_id": text(r.get("build_id")),
                "n": int(r["n"]),
                "first": iso(r["first"]),
                "last": iso(r["last"]),
            }
            for r in versions.to_dict("records")
        ],
        "bands": [
            {"band": str(r["band"]), "n": int(r["n"]), "approve_share": round(int(r["approve"] or 0) / int(r["n"]), 4)}
            for r in bands.to_dict("records")
        ],
        "reasons": reasons[:12],
        "recent": [_row(r) for r in recent.to_dict("records")],
    }


def detail(decision_id: str) -> dict | None:
    from lau.decision.notices import notice

    st = deps.ui_store()
    if not available():
        return None
    df = query(
        st,
        f"SELECT {ROW_COLUMNS}, reasons_json, unmapped_reasons, code_version, is_test "
        f"FROM {_table(st)} WHERE decision_id = {sql_str(decision_id)} LIMIT 1",
        ts=["decided_at"],
    )
    if df.empty:
        return None
    r = df.iloc[0].to_dict()
    n = notice(decision_id, store=st) or {}
    shadow = None
    if text(r.get("shadow_model_version")):
        shadow = {
            "model_version": text(r.get("shadow_model_version")),
            "decision": text(r.get("shadow_decision")),
            "probability_of_default": num(r.get("shadow_probability_of_default")),
        }
    return {
        **_row(r),
        "definition_version": text(r.get("definition_version")),
        "build_id": text(r.get("build_id")),
        "code_version": text(r.get("code_version")),
        "fallback_reason": text(r.get("fallback_reason")),
        "reasons_missing": bool(boolean(r.get("reasons_missing"))),
        "client_latency_ms": num(r.get("client_latency_ms")),
        "source": text(r.get("source")),
        "is_test": bool(boolean(r.get("is_test"))),
        "reasons": [
            {
                "rank": i + 1,
                "code": x.get("code"),
                "statement": x.get("statement"),
                "feature": x.get("feature"),
                "mapped": bool(x.get("mapped", True)),
            }
            for i, x in enumerate(loads(r.get("reasons_json"), []) or [])
        ],
        "notice": {
            "required": bool(n.get("notice_required")),
            "principal_reasons": n.get("principal_reasons", []),
            "caveat": n.get("caveat"),
        },
        "shadow": shadow,
    }


def search(q: str, limit: int = 20) -> list[dict]:
    st = deps.ui_store()
    if not available() or not q.strip():
        return []
    like = sql_str(q.strip() + "%")
    df = query(
        st,
        f"SELECT {ROW_COLUMNS} FROM {_table(st)} WHERE decision_id LIKE {like} OR application_id LIKE {like} "
        f"ORDER BY decided_at DESC LIMIT {int(limit)}",
        ts=["decided_at"],
    )
    return [_row(r) for r in df.to_dict("records")]


# ---- rollouts --------------------------------------------------------------------------------------------------------
@ttl_cache(10)
def rollouts_list() -> list[dict]:
    from lau.decision import rollout

    st = deps.ui_store()
    try:
        return rollout.rollouts(st)
    except Exception:  # noqa: BLE001 - not visible yet
        return []


def rollouts_view() -> dict:
    from lau.decision import rollout
    from lau.governance.approvals import required, tally

    st = deps.ui_store()
    out = []
    for r in rollouts_list():
        recorded = rollout.decisions_recorded(r["rollout_id"], st)
        t = tally(recorded)
        try:
            report = rollout.report(r["rollout_id"], st)
        except Exception:  # noqa: BLE001 - no decisions yet
            report = {"n": 0}
        out.append(
            {
                "rollout_id": r["rollout_id"],
                "state": r["state"],
                "model_version": r["model_version"],
                "definition_version": r["definition_version"],
                "promotion_id": text(r.get("promotion_id")),
                "started_at": iso(r["started_at"]),
                "started_by": r["started_by"],
                "updated_at": iso(r["updated_at"]),
                "previous_serving_version": r["previous_serving_version"],
                "events": [
                    {
                        "event": str(e["event"]),
                        "state": str(e["state"]),
                        "ts": iso(e["ts"]),
                        "by": str(e["by_user"]),
                        "note": text(e.get("note")),
                    }
                    for e in r["events"]
                ],
                "approvals": {
                    "required": required("rollout"),
                    "approvers": t["approvers"],
                    "rejected_by": t["rejected_by"],
                    "decisions": [
                        {
                            "approver": str(d["approver"]),
                            "decision": str(d["decision"]),
                            "note": text(d.get("note")),
                            "ts": iso(d.get("ts")),
                        }
                        for d in recorded
                    ],
                },
                "report": json.loads(json.dumps(report, default=str)),
            }
        )
    rules = get_settings().decisioning.get("rollout", {})
    return {
        "rollouts": out,
        "min_shadow_decisions": int(rules.get("min_shadow_decisions", 0)),
        "required_approvals": required("rollout"),
    }
