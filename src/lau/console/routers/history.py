"""Console API (screen 5, history and change log):
- GET /api/events?[types]&[definition]&[before]&[limit]
- GET /api/changes?from&to
- GET /api/cycles, GET /api/cycles/{cycle_id}
- GET /api/lineage/{model_name}/{version}

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

import pandas as pd
from fastapi import HTTPException, Query

from lau.console.services import definitions as defs
from lau.console.services import evals, events, models, ops, reports
from lau.console.util import api_router, iso, parse_ts, safe_token, short, text

router = api_router()


@router.get("/events")
def events_page(
    types: str | None = None, definition: str | None = None, before: str | None = None, limit: int = 100
) -> dict:
    wanted = [t for t in (types or "").split(",") if t in events.EVENT_TYPES]
    version = defs.resolve_version(definition) if definition else None
    return events.page(wanted or None, version, parse_ts(before), limit)


def _vector(ts: pd.Timestamp) -> dict[str, tuple[str | None, str | None, str | None]]:
    """{component: (value, detail, href)} in effect at `ts`."""
    out: dict[str, tuple[str | None, str | None, str | None]] = {}
    active = None
    for h in defs._load()["history"]:
        if h["activated_at"] is not None and pd.Timestamp(h["activated_at"]) <= ts:
            active = h["version"]
    ref = defs.definition_ref(active)
    out["definition"] = (active, ref["summary"] if ref else None, f"/definitions/{active}" if active else None)
    data = ops.data_version_at(ts)
    dv = str(data["data_version"]) if data else None
    out["data"] = (dv, f"performance through {data['as_of_month']}" if data else None, None)
    serving = None
    promos = models.promotions()
    if len(promos):
        live = promos[(promos["ts"] <= ts) & promos["serving"].fillna(False).astype(bool)]
        if len(live):
            serving = str(live.iloc[0]["production_model_version"])
    _, prod = models.names()
    out["serving_model"] = (
        f"v{serving}" if serving else "legacy_score",
        None if serving else models.REFERENCE_LABEL,
        f"/models/{prod}/{serving}" if serving else None,
    )
    reg = models.registry()
    challenger = None
    if len(reg):
        created = reg[reg["created_at"].notna() & (pd.to_datetime(reg["created_at"], utc=True) <= ts)]
        ch = created[created["status"] == "challenger"]
        if len(ch):
            challenger = ch.iloc[0]
    out["challenger"] = (
        f"v{challenger['version']}" if challenger is not None else None,
        None,
        f"/models/{challenger['model_name']}/{challenger['version']}" if challenger is not None else None,
    )
    for comp, h in ops.config_vector_at(ts).items():
        out[f"config:{comp}"] = (h[:12], None, "/settings")
    return out


@router.get("/changes")
def changes_between(from_: str = Query(..., alias="from"), to: str = Query(...)) -> dict:
    a, b = parse_ts(from_), parse_ts(to)
    if a is None or b is None:
        raise HTTPException(status_code=400, detail="from and to must be ISO-8601 timestamps")
    before, after = _vector(a), _vector(b)
    components = []
    for comp in sorted(set(before) | set(after), key=lambda c: (c.startswith("config:"), c)):
        b_val, _, _ = before.get(comp, (None, None, None))
        a_val, a_detail, a_href = after.get(comp, (None, None, None))
        components.append(
            {
                "component": comp,
                "before": b_val,
                "after": a_val,
                "changed": b_val != a_val,
                "detail": a_detail,
                "href": a_href,
            }
        )
    return {"from": iso(a), "to": iso(b), "components": components, "events_between": events.between(a, b)}


@router.get("/cycles")
def cycles() -> list[dict]:
    df = ops.cycles()
    return [ops.cycle_summary(r) for r in df.to_dict("records")] if len(df) else []


@router.get("/cycles/{cycle_id}")
def cycle(cycle_id: str) -> dict:
    if not safe_token(cycle_id):
        raise HTTPException(status_code=400, detail="invalid cycle id")
    row = ops.cycle_row(cycle_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown cycle")
    return {
        **ops.cycle_summary(row),
        "plan": ops.cycle_plan(cycle_id),
        "steps": ops.cycle_steps(cycle_id, row["started_at"]),
        "reports": reports.for_cycle(cycle_id),
        "trace": ops.trace_entries(cycle_id, limit=2000),
        "report_markdown": ops.cycle_report_markdown(cycle_id),
    }


@router.get("/lineage/{model_name}/{version}")
def lineage(model_name: str, version: str) -> dict:
    row = models.registry_row(model_name, version)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown model version")
    cand_name, prod_name = models.names()
    nodes: list[dict] = []
    edges: list[dict] = []

    def node(id_: str, type_: str, label: str, detail: str | None = None, href: str | None = None) -> str:
        if all(n["id"] != id_ for n in nodes):
            nodes.append({"id": id_, "type": type_, "label": label, "detail": detail, "href": href})
        return id_

    def edge(a: str, b: str) -> None:
        edges.append({"from": a, "to": b})

    source_version = (
        str(row.get("source_candidate_version") or row["version"]) if model_name == prod_name else row["version"]
    )
    cand_row = models.registry_row(cand_name, source_version)
    role = (cand_row or row).get("lau_role")
    ref = f"{'baseline' if role == 'baseline' else 'candidate'}:{source_version}"
    definition = row.get("definition_version")
    created = row.get("created_at")
    data = ops.data_version_at(pd.Timestamp(created)) if created is not None and not pd.isna(created) else None

    d_id = None
    if data:
        d_id = node(
            f"data:{data['data_version']}",
            "data",
            f"Data {short(str(data['data_version']))}",
            f"{int(data['n_applications'] or 0):,} applications, performance through {data['as_of_month']}",
        )
    def_id = None
    if definition:
        dref = defs.definition_ref(definition)
        def_id = node(
            f"definition:{definition}",
            "definition",
            dref["summary"] if dref else short(definition) or "",
            dref["short"] if dref else None,
            f"/definitions/{definition}",
        )
        stats = defs.label_stats_by_version().get(definition)
        lab = node(
            f"labels:{definition}",
            "labels",
            "Labels",
            f"{stats['n_default']:,} defaults of {stats['n_eligible']:,} eligible loans" if stats else None,
            f"/definitions/{definition}",
        )
        edge(def_id, lab)
        if d_id:
            edge(d_id, lab)
        def_id = lab
    _, res = evals.latest_result(ref)
    feats = (res.get("model") or {}).get("features") or []
    eng = (res.get("model") or {}).get("engineered") or []
    f_id = node(
        f"features:{ref}",
        "features",
        f"{len(feats)} features" + (f", {len(eng)} engineered" if eng else ""),
        ", ".join(list(feats)[:12]) or None,
        "/features",
    )
    if def_id:
        edge(def_id, f_id)
    run_id = row.get("run_id")
    r_id = node(f"run:{run_id}", "run", "Training run", text(run_id)) if run_id else None
    if r_id:
        edge(f_id, r_id)
    c_ref = models.ref_from_row(cand_row) if cand_row else models.ref_for_candidate(ref)
    c_id = node(
        f"model:{c_ref['key']}",
        "model",
        f"Candidate {c_ref['label']}",
        None,
        f"/models/{c_ref['name']}/{c_ref['version']}",
    )
    edge(r_id or f_id, c_id)
    last = c_id
    ev = evals.evaluations()
    for e in evals.summaries(ev[ev["candidate_ref"] == ref] if len(ev) else ev):
        e_id = node(
            f"evaluation:{e['eval_id']}",
            "evaluation",
            f"Validation AUC {e['val_auc']:.4f}",
            "passed" if e["passed_validation"] else "did not pass",
            f"/performance/evaluations/{e['eval_id']}",
        )
        edge(c_id, e_id)
        last = e_id
    g = evals.latest_gate_row(ref)
    if g:
        gs = evals.gate_summary(g)
        g_id = node(
            f"gate:{gs['gate_id']}",
            "gate",
            "Holdout gate " + ("passed" if gs["passed"] else "failed"),
            f"holdout AUC {gs['holdout_auc']:.4f}",
            f"/approvals/{ref}",
        )
        edge(last, g_id)
        last = g_id
    for a in evals.approvals_for(ref)[:1]:
        a_id = node(
            f"approval:{a['approval_id']}",
            "approval",
            f"{a['decision'].capitalize()}d by {a['approver']}",
            a["rationale"][:200],
        )
        edge(last, a_id)
        last = a_id
    promo = models.promotion_for_candidate(source_version)
    if promo:
        p_id = node(
            f"promotion:{promo['promotion_id']}",
            "promotion",
            f"Promoted to production v{promo['production_model_version']}",
            "serving" if promo.get("serving") else "champion for its definition",
            f"/models/{prod_name}/{promo['production_model_version']}",
        )
        edge(last, p_id)
    return {"nodes": nodes, "edges": edges}
