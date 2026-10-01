"""Adverse-action content for one decision: principal reasons as an applicant reads them, plus what reviewers need.

Not a compliant notice by itself: counsel approves the statement list, the notice text, timing and delivery
(Regulation B, FCRA) before anything is sent. A refer is not adverse until a person declines it.
"""

from __future__ import annotations

import json

from lau.store import get_store


def notice(decision_id: str, store=None) -> dict | None:
    st = store or get_store("harness")
    if not st.table_exists("ops", "decisions"):
        return None
    did = decision_id.replace("'", "''")
    df = st.query(f"SELECT * FROM {st.fq('ops', 'decisions')} WHERE decision_id = '{did}' LIMIT 1")
    if df.empty:
        return None
    r = df.iloc[0].to_dict()
    reasons = json.loads(r.get("reasons_json") or "[]")
    adverse = r["decision"] == "decline"
    return {
        "decision_id": decision_id,
        "application_id": r["application_id"],
        "decision": r["decision"],
        "decided_at": str(r["decided_at"]),
        "path": r["path"],
        "notice_required": adverse,
        "principal_reasons": [
            {"rank": i + 1, "code": x["code"], "statement": x["statement"]} for i, x in enumerate(reasons)
        ],
        "for_reviewers": {
            "features": [x.get("feature") for x in reasons],
            "unmapped_reasons": int(r.get("unmapped_reasons") or 0),
            "reasons_missing": bool(r.get("reasons_missing")),
            "probability_of_default": r.get("probability_of_default"),
            "risk_band": r.get("risk_band"),
            "fallback_used": bool(r.get("fallback_used")),
        },
        "versions": {
            k: r.get(k) for k in ("model_version", "definition_version", "policy_version", "build_id", "code_version")
        },
        "caveat": "Synthetic system. Statements, notice text and delivery need counsel's approval before use.",
    }
