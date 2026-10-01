"""Credit policy versions: config/policy.yaml, content-hashed like a definition of default, approval-gated.

Tables (ops schema, written by the harness identity): policy_versions (every version seen), policy_approvals (who
approved which hash), active_policy (activation history). A version becomes active only after the required number of
different people approved it (two-person rule in prod). The decision model always embeds the active version.
"""

from __future__ import annotations

import getpass
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from lau.settings import CONFIG_DIR

POLICY_PATH = CONFIG_DIR / "policy.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionSpec(_Strict):
    approve_max_pd: float = Field(gt=0, lt=1)
    refer_max_pd: float = Field(gt=0, lt=1)


class KnockoutSpec(_Strict):
    max_dti: float | None = Field(None, gt=0)
    min_bureau_score: float | None = None


class LegacySpec(_Strict):
    min_score: float


class Policy(_Strict):
    name: str
    decision: DecisionSpec
    knockouts: KnockoutSpec = KnockoutSpec()
    bands: dict[str, float]
    reason_codes: int = Field(4, ge=1, le=4)
    legacy: LegacySpec

    @model_validator(mode="after")
    def _check(self) -> Policy:
        if self.decision.refer_max_pd < self.decision.approve_max_pd:
            raise ValueError("refer_max_pd must be at least approve_max_pd")
        bounds = list(self.bands.values())
        if bounds != sorted(bounds) or bounds[-1] < 1.0:
            raise ValueError("bands must be increasing PD upper bounds ending at 1.0")
        return self

    def semantic(self) -> dict:
        """What decides: everything except the display name."""
        return {k: v for k, v in self.model_dump().items() if k != "name"}


class PolicyNotActiveError(RuntimeError):
    pass


def load_policy(path: Path | None = None) -> Policy:
    return Policy(**(yaml.safe_load(Path(path or POLICY_PATH).read_text()) or {}))


def policy_version(p: Policy) -> str:
    canon = json.dumps(p.semantic(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:12]


def _now() -> datetime:
    return datetime.now(UTC)


def _store():
    from lau.store import get_store

    return get_store("harness")


def register(p: Policy, by: str | None = None) -> str:
    st, v = _store(), policy_version(p)
    if st.table_exists("ops", "policy_versions"):
        hit = st.query(f"SELECT policy_version FROM {st.fq('ops', 'policy_versions')} WHERE policy_version = '{v}'")
        if len(hit):
            return v
    row = {
        "policy_version": v,
        "name": p.name,
        "policy_json": json.dumps(p.model_dump(), sort_keys=True),
        "created_at": _now(),
        "created_by": by or getpass.getuser(),
    }
    st.write_df("ops", "policy_versions", pd.DataFrame([row]), mode="append")
    return v


def approvers(version: str) -> list[str]:
    st = _store()
    if not st.table_exists("ops", "policy_approvals"):
        return []
    df = st.query(
        f"SELECT approved_by FROM {st.fq('ops', 'policy_approvals')} "
        f"WHERE policy_version = '{version}' ORDER BY approved_at"
    )
    out: list[str] = []
    for who in df["approved_by"] if len(df) else []:
        if str(who) not in out:
            out.append(str(who))
    return out


def record_approval(p: Policy, approver: str, note: str = "") -> str:
    v = register(p, approver)
    if approver in approvers(v):
        return v
    row = {
        "approval_id": f"polapr-{v}-{int(_now().timestamp())}",
        "policy_version": v,
        "approved_by": approver,
        "approved_at": _now(),
        "note": note[:2000],
    }
    _store().write_df("ops", "policy_approvals", pd.DataFrame([row]), mode="append")
    return v


def active() -> tuple[str, Policy] | None:
    st = _store()
    if not st.table_exists("ops", "active_policy"):
        return None
    df = st.query(
        f"SELECT a.policy_version, v.policy_json FROM {st.fq('ops', 'active_policy')} a "
        f"JOIN {st.fq('ops', 'policy_versions')} v ON a.policy_version = v.policy_version "
        "ORDER BY a.activated_at DESC LIMIT 1"
    )
    if df.empty:
        return None
    return str(df["policy_version"].iloc[0]), Policy(**json.loads(df["policy_json"].iloc[0]))


def plan(path: Path | None = None) -> dict:
    from lau.governance.approvals import required

    p = load_policy(path)
    v = policy_version(p)
    current = active()
    diff = []
    if current is None or current[0] != v:
        old = current[1].semantic() if current else {}
        new = p.semantic()
        for k in sorted(set(old) | set(new)):
            if old.get(k) != new.get(k):
                diff.append({"field": k, "before": old.get(k), "after": new.get(k)})
    return {
        "version": v,
        "name": p.name,
        "active": current[0] if current else None,
        "is_noop": current is not None and current[0] == v,
        "diff": diff,
        "approvers": approvers(v),
        "required": required("policy"),
    }


def apply(path: Path | None = None, by: str | None = None) -> dict:
    """Activate the policy in config/policy.yaml once it has the required approvals."""
    from lau.governance.approvals import required

    p = load_policy(path)
    v = register(p, by)
    have, need = len(approvers(v)), required("policy")
    if have < need:
        raise PolicyNotActiveError(f"{have} of {need} required approvals for policy {v}; run `lau policy approve`")
    current = active()
    if current is not None and current[0] == v:
        return {"version": v, "changed": False}
    row = {
        "policy_version": v,
        "previous_version": current[0] if current else None,
        "activated_at": _now(),
        "activated_by": by or getpass.getuser(),
    }
    _store().write_df("ops", "active_policy", pd.DataFrame([row]), mode="append")
    return {"version": v, "changed": True, "previous": row["previous_version"]}
