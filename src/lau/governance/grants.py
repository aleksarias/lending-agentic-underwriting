"""Single source of truth for who may read/write what.

The same `GRANTS` list is used to:
  * emit Unity Catalog GRANT statements (`grant_statements`), and
  * enforce an identical ACL in-process for every Store (defense in depth, and so offline tests are faithful).

Roles:
  admin    - the human (you). Owns everything; not restricted by this ACL.
  harness  - evaluation harness + deterministic pipeline identity. Only principal that can read `holdout`.
  agent    - identity for every agent tool call. Read-only curated/labels (active views only), r/w experiments
             and feature_registry. No grants on raw, holdout, production, ops.
  promoter - writes `production`, only via `lau promote` after a recorded human approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Level = Literal["CATALOG", "SCHEMA", "TABLE", "VOLUME"]

READ_PRIVS = {"SELECT", "ALL PRIVILEGES"}
WRITE_PRIVS = {"MODIFY", "ALL PRIVILEGES"}
CREATE_PRIVS = {"CREATE TABLE", "ALL PRIVILEGES"}


@dataclass(frozen=True)
class Grant:
    role: str
    level: Level
    schema: str | None = None  # logical schema key
    obj: str | None = None  # table / view / volume name for TABLE/VOLUME level
    privileges: tuple[str, ...] = ()


ALL = ("ALL PRIVILEGES",)
RO_SCHEMA = ("USE SCHEMA", "SELECT", "EXECUTE")
RW_SCHEMA = ("USE SCHEMA", "SELECT", "MODIFY", "CREATE TABLE", "CREATE MODEL", "EXECUTE", "READ VOLUME", "WRITE VOLUME")

# Objects the agent role may read in otherwise-restricted schemas (created by the pipeline).
AGENT_READABLE_OBJECTS = {
    "curated": ["applications_dev", "data_catalog"],
    "labels": ["labels_active"],
}

GRANTS: list[Grant] = [
    # --- harness / pipeline identity ---------------------------------------------------------------
    Grant("harness", "CATALOG", privileges=("USE CATALOG",)),
    *[
        Grant("harness", "SCHEMA", s, privileges=ALL)
        for s in ("curated", "labels", "feature_registry", "experiments", "holdout", "ops")
    ],
    Grant("harness", "SCHEMA", "raw", privileges=("USE SCHEMA", "SELECT", "READ VOLUME")),
    Grant("harness", "SCHEMA", "production", privileges=RO_SCHEMA),
    # --- agent ------------------------------------------------------------------------------------------
    Grant("agent", "CATALOG", privileges=("USE CATALOG",)),
    Grant("agent", "SCHEMA", "curated", privileges=("USE SCHEMA",)),
    Grant("agent", "SCHEMA", "labels", privileges=("USE SCHEMA",)),
    *[
        Grant("agent", "TABLE", schema, obj, ("SELECT",))
        for schema, objs in AGENT_READABLE_OBJECTS.items()
        for obj in objs
    ],
    Grant("agent", "SCHEMA", "experiments", privileges=RW_SCHEMA),
    Grant("agent", "SCHEMA", "feature_registry", privileges=RW_SCHEMA),
    # --- promoter -----------------------------------------------------------------------------------
    Grant("promoter", "CATALOG", privileges=("USE CATALOG",)),
    Grant("promoter", "SCHEMA", "production", privileges=ALL),
    Grant("promoter", "SCHEMA", "experiments", privileges=RO_SCHEMA),
    Grant("promoter", "SCHEMA", "ops", privileges=("USE SCHEMA", "SELECT")),
]


def _privs(role: str, schema: str, obj: str | None) -> set[str]:
    out: set[str] = set()
    for g in GRANTS:
        if g.role != role:
            continue
        if g.level == "SCHEMA" and g.schema == schema:
            out |= set(g.privileges)
        if g.level == "TABLE" and g.schema == schema and obj is not None and g.obj == obj.lower():
            out |= set(g.privileges)
    return out


def can_read(role: str, schema: str, obj: str | None) -> bool:
    if role == "admin":
        return True
    return bool(_privs(role, schema, obj) & READ_PRIVS)


def can_write(role: str, schema: str, obj: str | None) -> bool:
    if role == "admin":
        return True
    privs = _privs(role, schema, obj)
    return bool(privs & WRITE_PRIVS) or bool(privs & CREATE_PRIVS)


def readable_schemas(role: str) -> set[str]:
    return {
        g.schema for g in GRANTS if g.role == role and g.schema and set(g.privileges) & (READ_PRIVS | {"USE SCHEMA"})
    }


def grant_statements(
    settings, principal_ids: dict[str, str], objects_only: bool = False, skip_objects: bool = False
) -> list[str]:
    """UC GRANT statements. principal_ids maps role -> SP application_id (UC principal for SPs).

    objects_only=True emits only TABLE-level grants (re-applied after views are (re)created).
    """
    stmts: list[str] = []
    for g in GRANTS:
        pid = principal_ids.get(g.role)
        if not pid:
            continue
        if objects_only and g.level != "TABLE":
            continue
        if skip_objects and g.level == "TABLE":  # views don't exist until the pipeline creates them
            continue
        privs = ", ".join(g.privileges)
        if g.level == "CATALOG":
            target = f"CATALOG `{settings.catalog}`"
        elif g.level == "SCHEMA":
            target = f"SCHEMA `{settings.catalog}`.`{settings.schema(g.schema)}`"
        elif g.level == "TABLE":
            target = f"TABLE `{settings.catalog}`.`{settings.schema(g.schema)}`.`{g.obj}`"
        else:
            target = f"VOLUME `{settings.catalog}`.`{settings.schema(g.schema)}`.`{g.obj}`"
        stmts.append(f"GRANT {privs} ON {target} TO `{pid}`")
    return stmts
