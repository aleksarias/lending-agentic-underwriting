"""Definition version registry (ops schema): known versions, the active pointer (append-only history), approvals.

`ops.active_definition` is append-only: the latest row is the active version. Old versions stay queryable forever.
"""

from __future__ import annotations

import getpass
import json
from datetime import UTC, datetime

import pandas as pd

from lau.definition.hashing import canonical_json, definition_version
from lau.definition.schema import DefaultDefinition, definition_from_dict
from lau.store import Store


def _now() -> datetime:
    return datetime.now(UTC)


def register_version(store: Store, defn: DefaultDefinition, created_by: str) -> str:
    version = definition_version(defn)
    if store.table_exists("ops", "definition_versions"):
        existing = store.query(
            f"SELECT count(*) AS n FROM {store.fq('ops', 'definition_versions')} WHERE definition_version = '{version}'"
        )
        if int(existing["n"].iloc[0]):
            return version
    store.write_df(
        "ops",
        "definition_versions",
        pd.DataFrame(
            [
                {
                    "definition_version": version,
                    "name": defn.metadata.name,
                    "description": defn.metadata.description,
                    "canonical_json": canonical_json(defn),
                    "full_json": defn.model_dump_json(),
                    "created_at": _now(),
                    "created_by": created_by,
                }
            ]
        ),
        mode="append",
    )
    return version


def get_definition(store: Store, version: str) -> DefaultDefinition:
    df = store.query(
        f"SELECT full_json FROM {store.fq('ops', 'definition_versions')} WHERE definition_version = '{version}'"
    )
    if df.empty:
        raise KeyError(f"unknown definition_version {version}")
    return definition_from_dict(json.loads(df["full_json"].iloc[0]))


def active_version(store: Store) -> str | None:
    if not store.table_exists("ops", "active_definition"):
        return None
    df = store.query(
        f"SELECT definition_version FROM {store.fq('ops', 'active_definition')} ORDER BY activated_at DESC LIMIT 1"
    )
    return None if df.empty else str(df["definition_version"].iloc[0])


def activation_history(store: Store) -> pd.DataFrame:
    if not store.table_exists("ops", "active_definition"):
        return pd.DataFrame()
    return store.query(f"SELECT * FROM {store.fq('ops', 'active_definition')} ORDER BY activated_at")


def set_active(store: Store, version: str, activated_by: str, approval_id: str | None = None) -> str | None:
    previous = active_version(store)
    if previous == version:
        return previous
    store.write_df(
        "ops",
        "active_definition",
        pd.DataFrame(
            [
                {
                    "definition_version": version,
                    "previous_version": previous,
                    "activated_at": _now(),
                    "activated_by": activated_by,
                    "approval_id": approval_id,
                }
            ]
        ),
        mode="append",
    )
    return previous


def approvers(store: Store, version: str) -> list[str]:
    """Distinct people who approved this exact definition hash, oldest first."""
    if not store.table_exists("ops", "definition_approvals"):
        return []
    df = store.query(
        f"SELECT approved_by FROM {store.fq('ops', 'definition_approvals')} "
        f"WHERE definition_version = '{version}' ORDER BY approved_at"
    )
    out: list[str] = []
    for who in df["approved_by"] if len(df) else []:
        if str(who) not in out:
            out.append(str(who))
    return out


def record_approval(store: Store, version: str, plan_summary: str, approver: str | None = None) -> str:
    who = approver or getpass.getuser()
    if who in approvers(store, version):  # one person approves a hash once: the two-person rule counts people
        return find_approval(store, version) or ""
    approval_id = f"defapr-{version}-{int(_now().timestamp())}"
    store.write_df(
        "ops",
        "definition_approvals",
        pd.DataFrame(
            [
                {
                    "approval_id": approval_id,
                    "definition_version": version,
                    "approved_by": who,
                    "approved_at": _now(),
                    "plan_summary": plan_summary[:8000],
                }
            ]
        ),
        mode="append",
    )
    return approval_id


def find_approval(store: Store, version: str) -> str | None:
    if not store.table_exists("ops", "definition_approvals"):
        return None
    df = store.query(
        f"SELECT approval_id FROM {store.fq('ops', 'definition_approvals')} "
        f"WHERE definition_version = '{version}' ORDER BY approved_at DESC LIMIT 1"
    )
    return None if df.empty else str(df["approval_id"].iloc[0])


def diff_definitions(old: DefaultDefinition | None, new: DefaultDefinition) -> list[tuple[str, object, object]]:
    if old is None:
        return [(k, None, v) for k, v in new.semantic_dict().items()]
    o, n = old.semantic_dict(), new.semantic_dict()
    return [(k, o.get(k), n.get(k)) for k in sorted(set(o) | set(n)) if o.get(k) != n.get(k)]
