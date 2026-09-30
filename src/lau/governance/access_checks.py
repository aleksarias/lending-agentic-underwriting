"""Access probes: does each identity see exactly what `lau.governance.grants` says it should?

Every probe is `SELECT * ... LIMIT 1` as the role under test. On Databricks it goes through
`DatabricksStore._query`, which skips the in-process ACL, so Unity Catalog alone decides; on the local backend
`Store.query` runs the in-process ACL (the same grants spec). Each result is one row of `ops.access_checks`:

    checked_at, role, object ("schema.table"), expected (allow|deny), observed (allow|deny|error), ok, detail

`error` means the probe could not tell (missing table, warehouse problem): it is never `ok`, because an unproven
denial is not a denial. All rows of one run share `checked_at`, so the latest run is `max(checked_at)`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from lau.redact import redact_text
from lau.settings import Settings, get_settings
from lau.store import AccessDeniedError, Store, get_store

# role -> objects it must not read / must read, as "schema.table" with logical schema keys.
PROBES: dict[str, dict[str, list[str]]] = {
    "agent": {
        "deny": [
            "holdout.oot_labels",
            "labels.labels_all",
            "raw.protected_attributes",
            "raw.performance",
            "curated.applications",
            "ops.pipeline_state",
        ],
        "allow": ["labels.labels_active", "curated.applications_dev", "curated.data_catalog"],
    },
    "ui": {
        "deny": [
            "raw.performance",
            "holdout.oot_labels",
            "labels.labels_all",
            "curated.applications",
            "curated.cashflow_monthly",
        ],
        "allow": ["ops.cycles", "curated.data_catalog", "labels.split_meta", "experiments.reports"],
    },
    "promoter": {"deny": ["holdout.oot_labels"], "allow": []},
}
DENIED_MARKERS = ("PERMISSION_DENIED", "INSUFFICIENT_PERMISSIONS", "does not have")


def _is_denied(e: Exception) -> bool:
    return isinstance(e, AccessDeniedError) or any(m in str(e) for m in DENIED_MARKERS)


def _probe(store: Store, role: str, obj: str, expected: str, checked_at: datetime) -> dict[str, Any]:
    schema, table = obj.split(".", 1)
    sql = f"SELECT * FROM {store.fq(schema, table)} LIMIT 1"
    # Databricks: `_query` skips the in-process ACL so Unity Catalog alone decides. Local: the in-process ACL.
    run = store._query if store.backend == "databricks" else store.query
    try:
        n = len(run(sql))
        observed, detail = "allow", f"readable ({n} row sampled)"
    except Exception as e:  # noqa: BLE001 - every failure is a result
        observed = "deny" if _is_denied(e) else "error"
        detail = redact_text(" ".join(str(e).split()))[:200]
    return {
        "checked_at": checked_at,
        "role": role,
        "object": obj,
        "expected": expected,
        "observed": observed,
        "ok": observed == expected,
        "detail": detail,
    }


def _store_for(role: str, s: Settings) -> Store | None:
    """The store to probe as; None when a Databricks role has no credentials in .env (nothing to probe with)."""
    if s.project.backend != "databricks":
        return get_store(role)
    from lau.credentials import has_role_credentials
    from lau.store import DatabricksStore

    return DatabricksStore(role, s) if has_role_credentials(role) else None


def record_access_checks(rows: list[dict[str, Any]]) -> None:
    """Append probe results to `ops.access_checks` as the harness identity."""
    if rows:
        get_store("harness").write_df("ops", "access_checks", pd.DataFrame(rows), mode="append")


def run_access_checks(write: bool = True) -> list[dict[str, Any]]:
    """Probe agent, ui and promoter; returns one result per probe and, with `write`, records them all."""
    s = get_settings()
    if s.project.backend == "databricks" and not s.state.warehouse_id:
        return []
    checked_at = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for role, spec in PROBES.items():
        store = _store_for(role, s)
        if store is None:
            continue
        try:
            for expected in ("deny", "allow"):
                rows += [_probe(store, role, obj, expected, checked_at) for obj in spec[expected]]
        finally:
            if store.backend == "databricks":
                store.close()  # type: ignore[attr-defined]
    if write:
        record_access_checks(rows)
    return rows
