"""What people tell the improvement loop directly, outside any approval: features they reject and hypotheses they
want tried next. Stored in ops (no agent grant), so agents read them only as the planner's context and cannot change
them.

  ops.feature_decisions   reject / restore a registered feature, with a reason. The harness enforces rejections:
                          a candidate using a rejected feature fails validation (check `no_rejected_features`).
  ops.pinned_hypotheses   pin / unpin a hypothesis; pinned ones are put in front of the planner every cycle.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import pandas as pd

from lau.store import get_store

FEATURE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _latest(table: str, key: str, store=None) -> pd.DataFrame:
    st = store or get_store("harness")
    if not st.table_exists("ops", table):
        return pd.DataFrame()
    df = st.query(f"SELECT * FROM {st.fq('ops', table)} ORDER BY ts")
    return df.drop_duplicates(key, keep="last")


# ---- features -----------------------------------------------------------------------------------------------------
def feature_decision(name: str, decision: str, reason: str, by: str) -> dict:
    if decision not in ("reject", "restore"):
        raise ValueError("decision must be reject or restore")
    if not FEATURE_NAME.match(name):
        raise ValueError("not a feature name")
    if len(reason.strip()) < 10:
        raise ValueError("a reason of at least 10 characters is required")
    row = {"feature": name, "decision": decision, "reason": reason.strip()[:2000], "by_user": by, "ts": _now()}
    get_store("harness").write_df("ops", "feature_decisions", pd.DataFrame([row]), mode="append")
    return row


def rejected_features(store=None) -> dict[str, dict]:
    """feature -> {reason, by_user, ts} for features whose latest decision is a rejection."""
    df = _latest("feature_decisions", "feature", store)
    if df.empty:
        return {}
    df = df[df["decision"] == "reject"]
    return {
        str(r["feature"]): {"reason": str(r["reason"]), "by_user": str(r["by_user"]), "ts": r["ts"]}
        for r in df.to_dict("records")
    }


# ---- hypotheses ---------------------------------------------------------------------------------------------------
def pin(text: str, by: str) -> dict:
    text = " ".join(text.split())
    if not 10 <= len(text) <= 500:
        raise ValueError("a hypothesis is 10 to 500 characters")
    row = {
        "hypothesis_id": f"hyp-{uuid.uuid4().hex[:8]}",
        "text": text,
        "status": "pinned",
        "by_user": by,
        "ts": _now(),
    }
    get_store("harness").write_df("ops", "pinned_hypotheses", pd.DataFrame([row]), mode="append")
    return row


def unpin(hypothesis_id: str, by: str) -> dict:
    current = {h["hypothesis_id"]: h for h in pinned()}
    if hypothesis_id not in current:
        raise ValueError(f"{hypothesis_id} is not pinned")
    row = {**current[hypothesis_id], "status": "unpinned", "by_user": by, "ts": _now()}
    get_store("harness").write_df("ops", "pinned_hypotheses", pd.DataFrame([row]), mode="append")
    return row


def pinned(store=None) -> list[dict]:
    df = _latest("pinned_hypotheses", "hypothesis_id", store)
    if df.empty:
        return []
    df = df[df["status"] == "pinned"]
    return [
        {"hypothesis_id": str(r["hypothesis_id"]), "text": str(r["text"]), "by_user": str(r["by_user"]), "ts": r["ts"]}
        for r in df.to_dict("records")
    ]
