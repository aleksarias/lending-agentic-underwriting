"""Console API: GET /api/readiness (production readiness: checklist, evidence, sign-offs). Read-only: sign-offs are
recorded by named people at a terminal (`lau readiness sign`), never from the console.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from lau.console import deps
from lau.console.util import api_router, iso

router = api_router()


@router.get("/readiness")
def readiness() -> dict:
    from lau.readiness import status, stored_evidence

    st = deps.ui_store()
    s = status(store=st, evidence_rows=stored_evidence(st) or {})
    for item in s["items"]:
        for r in item["signoffs"]:
            r["ts"] = iso(r["ts"]) if r["ts"] is not None else None
    return s
