"""Console API: GET /api/search?q (global search), POST /api/ask {question} (read-only question answering).

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from fastapi import Body, HTTPException, Request

from lau.console import deps
from lau.console.services import definitions as defs
from lau.console.services import models, ops, reports
from lau.console.util import api_router, read_table, sql_str, text

router = api_router()
MAX_RESULTS = 30


def _hit(q: str, *fields) -> bool:
    return any(q in str(f).lower() for f in fields if f)


@router.get("/search")
def search(q: str = "") -> list[dict]:
    q = q.strip().lower()
    if len(q) < 2:
        return []
    out: list[dict] = []
    for r in models.registry().to_dict("records"):
        tags = r.get("tags") or {}
        if _hit(
            q,
            f"v{r['version']}",
            r["version"],
            r["model_name"],
            tags.get("author"),
            tags.get("model_type"),
            r.get("status"),
        ):
            ref = models.ref_from_row(r)
            out.append(
                {
                    "type": "model",
                    "id": ref["key"],
                    "title": f"Model {ref['label']} ({r.get('status') or 'candidate'})",
                    "subtitle": " · ".join(x for x in (tags.get("model_type"), tags.get("author")) if x) or None,
                    "href": f"/models/{r['model_name']}/{r['version']}",
                }
            )
    for c in ops.cycles().to_dict("records") if len(ops.cycles()) else []:
        if _hit(q, c["cycle_id"], c.get("reason")):
            out.append(
                {
                    "type": "cycle",
                    "id": str(c["cycle_id"]),
                    "title": f"Cycle {c['cycle_id']}",
                    "subtitle": text(c.get("reason")),
                    "href": f"/history/cycles/{c['cycle_id']}",
                }
            )
    for d in defs.definition_refs():
        if _hit(q, d["version"], d["name"], d["summary"]):
            out.append(
                {
                    "type": "definition",
                    "id": d["version"],
                    "title": f"Definition {d['summary']}",
                    "subtitle": f"{d['name']} ({d['short']})",
                    "href": f"/definitions/{d['version']}",
                }
            )
    st = deps.ui_store()
    feats = read_table(st, "feature_registry", "features", columns=["name", "hypothesis", "author"])
    for r in feats.drop_duplicates("name").to_dict("records") if len(feats) else []:
        if _hit(q, r["name"], r.get("hypothesis")):
            out.append(
                {
                    "type": "feature",
                    "id": str(r["name"]),
                    "title": f"Feature {r['name']}",
                    "subtitle": (text(r.get("hypothesis")) or "")[:120] or None,
                    "href": "/features",
                }
            )
    active = defs.active_version()
    if active:
        cat = read_table(
            st,
            "curated",
            "data_catalog",
            columns=["variable", "description"],
            where=f"definition_version = {sql_str(active)}",
        )
        for r in cat.to_dict("records") if len(cat) else []:
            if _hit(q, r["variable"], r.get("description")):
                out.append(
                    {
                        "type": "variable",
                        "id": str(r["variable"]),
                        "title": f"Variable {r['variable']}",
                        "subtitle": (text(r.get("description")) or "")[:120] or None,
                        "href": f"/data/{r['variable']}",
                    }
                )
    for m in reports.list_meta():
        if _hit(q, m["title"], m["report_id"], m["author"]):
            out.append(
                {
                    "type": "report",
                    "id": m["report_id"],
                    "title": m["title"],
                    "subtitle": f"{m['author']} report" + (f", {m['verdict']}" if m["verdict"] else ""),
                    "href": f"/agents/reports/{m['report_id']}",
                }
            )
    return out[:MAX_RESULTS]


@router.post("/ask")
async def ask(request: Request, body: dict = Body(...)) -> dict:
    from lau.console.ask import AskUnavailableError, answer
    from lau.cost import BudgetExceededError

    question = str(body.get("question") or "").strip()
    if len(question) < 3:
        raise HTTPException(status_code=400, detail="Ask a question.")
    if len(question) > 2000:
        raise HTTPException(status_code=400, detail="Keep the question under 2,000 characters.")
    try:
        return await answer(question, deps.current_user(request))
    except AskUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except BudgetExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
