"""Service principals, their OAuth secrets (written only to .env), warehouse and MLflow experiment permissions."""

from __future__ import annotations

from collections.abc import Callable

from lau.credentials import write_env_values
from lau.settings import Settings, WorkspaceState


def ensure_warehouse(w, s: Settings, state: WorkspaceState, log: Callable[[str], None]) -> str:
    from databricks.sdk.service.sql import (
        CreateWarehouseRequestWarehouseType,
        EditWarehouseRequestWarehouseType,
        EndpointTagPair,
        EndpointTags,
    )

    wh = s.project.warehouse
    for existing in w.warehouses.list():
        if existing.name == wh.name:
            log(f"warehouse {wh.name} exists ({existing.id}); reusing")
            return existing.id
    try:
        created = w.warehouses.create(
            name=wh.name,
            cluster_size=wh.cluster_size,
            auto_stop_mins=wh.auto_stop_mins,
            min_num_clusters=1,
            max_num_clusters=1,
            enable_serverless_compute=True,
            warehouse_type=CreateWarehouseRequestWarehouseType.PRO,
            tags=EndpointTags(custom_tags=[EndpointTagPair(key="project", value="lau")]),
        ).result()
        state.warehouse_created_by_project = True
        log(f"created warehouse {wh.name} ({created.id}), {wh.cluster_size}, auto-stop {wh.auto_stop_mins} min")
        return created.id
    except Exception as e:  # noqa: BLE001
        if "cannot create the resource" not in str(e).lower() or not wh.adopt_existing_if_quota:
            raise
        log(f"warehouse creation refused ({e}); adopting '{wh.adopt_existing_if_quota}' as approved")
    target = next((x for x in w.warehouses.list() if x.name == wh.adopt_existing_if_quota), None)
    if target is None:
        raise RuntimeError(f"warehouse '{wh.adopt_existing_if_quota}' not found to adopt")
    g = w.warehouses.get(target.id)
    if state.warehouse_original_settings is None:
        state.warehouse_original_settings = {
            "name": g.name,
            "cluster_size": g.cluster_size,
            "auto_stop_mins": g.auto_stop_mins,
            "min_num_clusters": g.min_num_clusters,
            "max_num_clusters": g.max_num_clusters,
            "enable_photon": g.enable_photon,
            "enable_serverless_compute": g.enable_serverless_compute,
        }
    w.warehouses.edit(
        g.id,
        name=g.name,
        cluster_size=wh.cluster_size,
        auto_stop_mins=wh.auto_stop_mins,
        min_num_clusters=1,
        max_num_clusters=1,
        enable_photon=g.enable_photon,
        enable_serverless_compute=True,
        warehouse_type=EditWarehouseRequestWarehouseType.PRO,
    )
    log(
        f"adopted warehouse {g.name} ({g.id}): {g.cluster_size}/{g.auto_stop_mins}min -> "
        f"{wh.cluster_size}/{wh.auto_stop_mins}min (original saved; restored on teardown)"
    )
    return g.id


def restore_adopted_warehouse(w, state: WorkspaceState, log: Callable[[str], None]) -> None:
    from databricks.sdk.service.sql import EditWarehouseRequestWarehouseType

    o = state.warehouse_original_settings
    if not o or not state.warehouse_id:
        return
    w.warehouses.edit(
        state.warehouse_id,
        name=o["name"],
        cluster_size=o["cluster_size"],
        auto_stop_mins=o["auto_stop_mins"],
        min_num_clusters=o["min_num_clusters"],
        max_num_clusters=o["max_num_clusters"],
        enable_photon=o["enable_photon"],
        enable_serverless_compute=o["enable_serverless_compute"],
        warehouse_type=EditWarehouseRequestWarehouseType.PRO,
    )
    log(f"restored warehouse {o['name']} to {o['cluster_size']}/{o['auto_stop_mins']}min")


def ensure_service_principals(w, s: Settings, state: WorkspaceState, log: Callable[[str], None]) -> None:
    from databricks.sdk.service import iam
    from databricks.sdk.service.sql import WarehouseAccessControlRequest, WarehousePermissionLevel

    for role, pcfg in s.project.principals.items():
        if not pcfg.sp_display_name:
            continue
        info = state.service_principals.get(role)
        if info is None:
            found = list(w.service_principals.list(filter=f'displayName eq "{pcfg.sp_display_name}"'))
            if found:
                sp = found[0]
                log(f"service principal {pcfg.sp_display_name} exists; reusing")
            else:
                sp = w.service_principals.create(
                    display_name=pcfg.sp_display_name,
                    active=True,
                    entitlements=[
                        iam.ComplexValue(value="workspace-access"),
                        iam.ComplexValue(value="databricks-sql-access"),
                    ],
                )
                log(f"created service principal {pcfg.sp_display_name}")
            info = {"id": sp.id, "application_id": sp.application_id, "display_name": pcfg.sp_display_name}
            state.service_principals[role] = info
        # OAuth secret -> .env only (never printed/logged)
        from lau.credentials import has_role_credentials

        if not has_role_credentials(role):
            secret = w.service_principal_secrets_proxy.create(info["id"])
            write_env_values(
                {
                    f"LAU_{role.upper()}_CLIENT_ID": info["application_id"],
                    f"LAU_{role.upper()}_CLIENT_SECRET": secret.secret,
                }
            )
            del secret
            log(f"OAuth secret for {pcfg.sp_display_name} written to .env")
        if state.warehouse_id:
            w.warehouses.update_permissions(
                state.warehouse_id,
                access_control_list=[
                    WarehouseAccessControlRequest(
                        service_principal_name=info["application_id"], permission_level=WarehousePermissionLevel.CAN_USE
                    )
                ],
            )


def grant_sp_user_role(w, sp_application_id: str, user_name: str, log: Callable[[str], None]) -> None:
    """Let `user_name` deploy jobs that run_as this SP (role servicePrincipal.user). Additive: keeps existing rules."""
    from databricks.sdk.service.iam import GrantRule, RuleSetUpdateRequest

    name = f"accounts/{w.config.account_id}/servicePrincipals/{sp_application_id}/ruleSets/default"
    current = w.account_access_control_proxy.get_rule_set(name=name, etag="")
    rules = list(current.grant_rules or [])
    principal = f"users/{user_name}"
    role = "roles/servicePrincipal.user"
    if any(r.role == role and principal in (r.principals or []) for r in rules):
        return
    rules.append(GrantRule(role=role, principals=[principal]))
    w.account_access_control_proxy.update_rule_set(
        name=name, rule_set=RuleSetUpdateRequest(name=name, etag=current.etag, grant_rules=rules)
    )
    log(f"granted {role} on SP {sp_application_id} to {user_name} (needed to deploy run_as jobs)")


def ensure_experiment(
    w,
    s: Settings,
    state: WorkspaceState,
    log: Callable[[str], None],
    path: str | None = None,
    levels: dict | None = None,
) -> str:
    """The agents' experiment by default; `path`/`levels` for another (decision builds: harness + promoter only)."""
    from databricks.sdk.service.ml import ExperimentAccessControlRequest, ExperimentPermissionLevel

    path = path or s.project.mlflow.experiment_path
    parent = path.rsplit("/", 1)[0]
    w.workspace.mkdirs(parent)
    exp = w.experiments.get_by_name(path) if _exists(w, path) else None
    exp_id = (
        exp.experiment.experiment_id
        if exp
        else w.experiments.create_experiment(path, tags=[_tag("project", "lau")]).experiment_id
    )
    levels = levels or {
        "harness": ExperimentPermissionLevel.CAN_MANAGE,
        "agent": ExperimentPermissionLevel.CAN_EDIT,
        "promoter": ExperimentPermissionLevel.CAN_READ,
    }
    acl = [
        ExperimentAccessControlRequest(
            service_principal_name=state.service_principals[r]["application_id"], permission_level=lvl
        )
        for r, lvl in levels.items()
        if r in state.service_principals
    ]
    w.experiments.update_permissions(exp_id, access_control_list=acl)
    log(f"MLflow experiment {path} ({exp_id}) with per-role permissions")
    return exp_id


def _exists(w, path: str) -> bool:
    try:
        w.experiments.get_by_name(path)
        return True
    except Exception:  # noqa: BLE001
        return False


def _tag(k: str, v: str):
    from databricks.sdk.service.ml import ExperimentTag

    return ExperimentTag(key=k, value=v)
