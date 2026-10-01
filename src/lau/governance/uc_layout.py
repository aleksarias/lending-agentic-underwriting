"""Unity Catalog layout (catalog, schemas, landing volumes), grants, warehouse, MLflow experiment, and teardown.

`plan_init()` returns the exact statements/actions (dry run). `run_init()` executes them as the admin identity and
records every created resource in .lau/workspace_state.json so `teardown` removes exactly what the project created.
"""

from __future__ import annotations

from collections.abc import Callable

from lau.governance.grants import grant_statements
from lau.settings import Settings, WorkspaceState, get_settings, save_state
from lau.store import LANDING_VOLUME, LocalStore, Store

# Schemas that receive DataFrame writes need a landing volume for staged parquet.
LANDING_SCHEMAS = ["raw", "curated", "labels", "feature_registry", "experiments", "holdout", "production", "ops"]
# The console snapshot (lau.console.snapshot): written by the harness identity, read by the console's ui identity.
CONSOLE_VOLUME = "console"
TAGS = "project = 'lau', managed_by = 'lending-agentic-underwriting'"


def schema_ddl(s: Settings) -> list[str]:
    out = []
    for key in s.project.schemas.model_fields:
        comment = {
            "holdout": "Out-of-time holdout. Harness principal only.",
            "production": "Champion models and promotion records. Promoter principal only.",
            "ops": "Pipeline state, approvals, traces, cost log.",
        }.get(key, f"lau {key}")
        out.append(f"CREATE SCHEMA IF NOT EXISTS `{s.catalog}`.`{s.schema(key)}` COMMENT '{comment}'")
    for key in LANDING_SCHEMAS:
        out.append(
            f"CREATE VOLUME IF NOT EXISTS `{s.catalog}`.`{s.schema(key)}`.`{LANDING_VOLUME}` "
            "COMMENT 'lau staging for parquet uploads'"
        )
    out.append(
        f"CREATE VOLUME IF NOT EXISTS `{s.catalog}`.`{s.schema('ops')}`.`{CONSOLE_VOLUME}` "
        "COMMENT 'Console snapshot: tables the ui role can read, mirrored by the local console'"
    )
    return out


def landing_volume_grants(s: Settings, ids: dict[str, str]) -> list[str]:
    """Each role may stage files only in the landing volumes of schemas it can write."""
    from lau.governance.grants import can_write

    out = []
    for role, pid in ids.items():
        for key in LANDING_SCHEMAS:
            if can_write(role, key, None):
                out.append(
                    f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{s.catalog}`.`{s.schema(key)}`."
                    f"`{LANDING_VOLUME}` TO `{pid}`"
                )
    console = f"`{s.catalog}`.`{s.schema('ops')}`.`{CONSOLE_VOLUME}`"
    if "harness" in ids:
        out.append(f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME {console} TO `{ids['harness']}`")
    if "ui" in ids:
        out.append(f"GRANT READ VOLUME ON VOLUME {console} TO `{ids['ui']}`")
    return out


def principal_ids(s: Settings) -> dict[str, str]:
    return {r: v["application_id"] for r, v in s.state.service_principals.items()}


def sp_roles(s: Settings, state: WorkspaceState | None = None) -> list[str]:
    """Roles backed by a service principal: the configured ones plus any already recorded in the workspace state."""
    configured = [r for r, p in s.project.principals.items() if p.sp_display_name]
    return configured + [r for r in (state.service_principals if state else {}) if r not in configured]


def apply_object_grants(st: Store) -> None:
    """(Re)apply TABLE-level grants for objects that exist (views/tables are created by different stages).
    No-op locally (the same ACL is enforced in code)."""
    if isinstance(st, LocalStore):
        return
    from lau.governance.grants import AGENT_READABLE_OBJECTS, UI_READABLE_OBJECTS

    s = st.s
    readable = [(k, o) for d in (AGENT_READABLE_OBJECTS, UI_READABLE_OBJECTS) for k, objs in d.items() for o in objs]
    existing = {(k, o) for k, o in readable if st.table_exists(k, o)}
    for stmt in grant_statements(s, principal_ids(s), objects_only=True):
        if any(f"`{s.schema(k)}`.`{o}`" in stmt for k, o in existing):
            st._execute(stmt)


def plan_init(s: Settings | None = None) -> list[str]:
    s = s or get_settings()
    lines = [
        f"-- 1. catalog: CREATE CATALOG IF NOT EXISTS `{s.project.catalog}` (fallback: schemas prefixed "
        f"'{s.project.schema_prefix_fallback}' in `{s.project.catalog_fallback}` if CREATE CATALOG is denied)",
        f"-- 2. SQL warehouse '{s.project.warehouse.name}': {s.project.warehouse.cluster_size}, serverless, "
        f"auto_stop={s.project.warehouse.auto_stop_mins} min, max 1 cluster",
        "-- 3. service principals (workspace-level) + OAuth secrets written to .env: "
        + ", ".join(f"{r}={p.sp_display_name}" for r, p in s.project.principals.items() if p.sp_display_name),
        "--    entitlements: workspace-access, databricks-sql-access; CAN_USE on the warehouse",
        f"-- 4. MLflow experiment {s.project.mlflow.experiment_path} (harness CAN_MANAGE, agent CAN_EDIT, "
        "promoter CAN_READ; ui none)",
        f"--    and {s.decisioning['experiment_path']} for decision-model builds (harness CAN_MANAGE, promoter "
        "CAN_READ; agent and ui none)",
        "-- 5. schemas + landing volumes:",
        *schema_ddl(s),
        "-- 6. grants (principal = SP application_id):",
        *grant_statements(s, {r: f"<{r}-sp-app-id>" for r in sp_roles(s)}),
        *landing_volume_grants(s, {r: f"<{r}-sp-app-id>" for r in sp_roles(s)}),
        "-- (TABLE-level grants on views labels_active / applications_dev / data_catalog are re-applied by the "
        "pipeline after the views are created)",
    ]
    return lines


# ---------------------------------------------------------------------------------------------------------
def run_init(log: Callable[[str], None] = print) -> WorkspaceState:
    s = get_settings()
    if s.project.backend == "local":
        st = LocalStore("admin", s)
        st.ensure_schemas()
        log(f"local lake ready at {s.local_lake}")
        return s.state

    from databricks.sdk import WorkspaceClient

    from lau.credentials import databricks_config
    from lau.governance import principals

    w = WorkspaceClient(config=databricks_config("admin"))
    state = s.state

    # 1. warehouse (needed to create the catalog: Default Storage catalogs are created via SQL on serverless)
    if not state.warehouse_id:
        state.warehouse_id = principals.ensure_warehouse(w, s, state, log)
        save_state(state)

    # 2. catalog
    if not state.catalog or state.schema_prefix:
        from lau.store import DatabricksStore

        admin = DatabricksStore("admin", get_settings())
        existed = any(c.name == s.project.catalog for c in w.catalogs.list())
        try:
            admin._execute(
                f"CREATE CATALOG IF NOT EXISTS `{s.project.catalog}` "
                "COMMENT 'lending-agentic-underwriting dev (synthetic data only)'"
            )
            state.catalog, state.schema_prefix = s.project.catalog, ""
            state.catalog_created_by_project = state.catalog_created_by_project or not existed
            log(f"catalog {s.project.catalog} ready")
        except Exception as e:  # noqa: BLE001
            state.catalog, state.schema_prefix = s.project.catalog_fallback, s.project.schema_prefix_fallback
            log(
                f"CREATE CATALOG failed ({str(e)[:160]}); falling back to `{state.catalog}` with schema prefix "
                f"'{state.schema_prefix}'"
            )
        admin.close()
        save_state(state)

    # 3. service principals + .env credentials
    principals.ensure_service_principals(w, s, state, log)
    save_state(state)
    if "harness" in state.service_principals:  # jobs run_as the harness SP
        principals.grant_sp_user_role(
            w, state.service_principals["harness"]["application_id"], w.current_user.me().user_name, log
        )

    s = get_settings()  # reload with state
    from lau.store import DatabricksStore

    st = DatabricksStore("admin", s)
    for stmt in schema_ddl(s):
        st._execute(stmt)
    log(f"schemas + landing volumes ready in {s.catalog}")
    ids = principal_ids(s)
    for stmt in grant_statements(s, ids, skip_objects=True) + landing_volume_grants(s, ids):
        st._execute(stmt)
    log(f"applied {len(grant_statements(s, ids, skip_objects=True))} schema/catalog grants + landing volume grants")

    # 4. MLflow experiment + permissions
    state.experiment_id = principals.ensure_experiment(w, s, state, log)
    from databricks.sdk.service.ml import ExperimentPermissionLevel as Lvl

    state.decision_experiment_id = principals.ensure_experiment(  # decision builds: no agent access at all
        w,
        s,
        state,
        log,
        path=s.decisioning["experiment_path"],
        levels={"harness": Lvl.CAN_MANAGE, "promoter": Lvl.CAN_READ},
    )
    save_state(state)
    return state


def run_teardown(log: Callable[[str], None] = print, yes: bool = False) -> None:
    s = get_settings()
    if s.project.backend == "local":
        import shutil

        from lau.store import reset_local_connections

        reset_local_connections()
        shutil.rmtree(s.local_lake, ignore_errors=True)
        log(f"removed local lake {s.local_lake}")
        return
    from databricks.sdk import WorkspaceClient

    from lau.credentials import databricks_config, write_env_values
    from lau.store import DatabricksStore

    w = WorkspaceClient(config=databricks_config("admin"))
    state = s.state
    # jobs from the bundle are removed by `databricks bundle destroy` (Makefile teardown runs it first)
    for exp_id in (state.experiment_id, state.decision_experiment_id):
        if not exp_id:
            continue
        try:
            w.experiments.delete_experiment(exp_id)
            log(f"deleted MLflow experiment {exp_id}")
        except Exception as e:  # noqa: BLE001
            log(f"experiment delete skipped: {e}")
    endpoint = s.decisioning["endpoint"]["name"]
    try:
        w.serving_endpoints.delete(endpoint)
        log(f"deleted serving endpoint {endpoint}")
    except Exception as e:  # noqa: BLE001 - never created, or already gone
        log(f"serving endpoint delete skipped: {type(e).__name__}")
    if state.catalog and state.warehouse_id:
        st = DatabricksStore("admin", s)
        # registered models live in schemas and are dropped with them (CASCADE)
        if state.catalog_created_by_project:
            st._execute(f"DROP CATALOG IF EXISTS `{state.catalog}` CASCADE")
            log(f"dropped catalog {state.catalog}")
        else:
            for key in s.project.schemas.model_fields:
                st._execute(f"DROP SCHEMA IF EXISTS `{state.catalog}`.`{s.schema(key)}` CASCADE")
            log(f"dropped project schemas in {state.catalog}")
        st.close()
    for role, sp in state.service_principals.items():
        try:
            w.service_principals.delete(sp["id"])
            log(f"deleted service principal {sp['display_name']} ({role})")
        except Exception as e:  # noqa: BLE001
            log(f"SP delete skipped for {role}: {e}")
    write_env_values({f"LAU_{r.upper()}_{k}": "" for r in sp_roles(s, state) for k in ("CLIENT_ID", "CLIENT_SECRET")})
    if state.warehouse_original_settings:
        from lau.governance.principals import restore_adopted_warehouse

        restore_adopted_warehouse(w, state, log)
    elif state.warehouse_id and state.warehouse_created_by_project:
        try:
            w.warehouses.delete(state.warehouse_id)
            log(f"deleted warehouse {state.warehouse_id}")
        except Exception as e:  # noqa: BLE001
            log(f"warehouse delete skipped: {e}")
    save_state(WorkspaceState())
    log("teardown complete; .lau/workspace_state.json reset; SP credentials blanked in .env")
