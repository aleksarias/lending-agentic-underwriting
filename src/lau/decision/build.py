"""Build, register and deploy the decision model from APPROVED state only.

What goes in: the champion behind the serving alias (none: the legacy policy decides), the champion in a shadow
rollout (if any), the ACTIVE policy (approved; there is no build without one), the reason statements and the
code version. The version vector and a build id travel with every decision.

  build    log the pyfunc (decision-build experiment, harness) and register it to <production>.decision_model as
           the promoter, alias `live`; a no-op when `live` already holds the same build
  deploy   point the Model Serving endpoint at a version. Creating the endpoint is compute: it happens only with
           create=True (`lau decision deploy --create`, run by a person); later updates run as the promoter
  publish  build, then update the endpoint if it exists (after promotions, rollouts and policy changes)
"""

from __future__ import annotations

import getpass
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pandas as pd

from lau.decision import policy as policies
from lau.decision import reasons
from lau.decision.pyfunc import DecisionModel, pip_requirements, signature
from lau.modeling import registry_io
from lau.settings import ROOT, get_settings
from lau.store import get_store

LIVE_ALIAS = "live"


def decision_model_name() -> str:
    s = get_settings()
    n = s.decisioning["decision_model"]
    return n if s.project.backend == "local" else s.fq("production", n)


def _code_version() -> str:
    from lau.versioning import _code_version

    return _code_version()[0]


def assemble() -> tuple[DecisionModel, dict]:
    """The decision model for the current approved state (nothing is written)."""
    s = get_settings()
    found = policies.active()
    if found is None:
        raise policies.PolicyNotActiveError(
            "no approved policy is active: review `lau policy plan`, approve with `lau policy approve`, "
            "then `lau policy apply`"
        )
    policy_version, policy = found
    prod = registry_io.production_model_name()
    serving = registry_io.serving_model("harness")
    serving_model = (
        registry_io.load_pd_model(f"models:/{prod}/{serving['model_version']}", "harness") if serving else None
    )
    from lau.decision import rollout

    shadow_version = rollout.shadow_version()
    shadow_model = registry_io.load_pd_model(f"models:/{prod}/{shadow_version}", "harness") if shadow_version else None
    versions = {
        "model_name": prod,
        "model_version": serving["model_version"] if serving else None,
        "definition_version": serving.get("definition_version") if serving else None,
        "policy_version": policy_version,
        "policy_name": policy.name,
        "shadow_model_version": shadow_version,
        "code_version": _code_version(),
    }
    versions["build_id"] = hashlib.sha256(json.dumps(versions, sort_keys=True).encode()).hexdigest()[:12]
    model = DecisionModel(
        serving=serving_model,
        shadow=shadow_model,
        policy=policy.model_dump(),
        reasons_lib=reasons.library(),
        versions=versions,
        months_history=int(s.synth["cashflow"]["months_history"]),
        timeout_ms=s.decisioning.get("timeout_ms"),
    )
    return model, versions


def live() -> tuple[str, dict] | None:
    """(registered version, tags) behind the `live` alias, or None before the first build."""
    return registry_io.alias_version(decision_model_name(), LIVE_ALIAS, "harness")


def build(log=print, by: str | None = None) -> dict:
    model, versions = assemble()
    current = live()
    if current is not None and current[1].get("build_id") == versions["build_id"]:
        log(f"decision model unchanged (build {versions['build_id']} is live as v{current[0]})")
        return {"version": current[0], "build_id": versions["build_id"], "changed": False, "versions": versions}
    import os

    import mlflow

    s = get_settings()
    # The serving environment is exactly pip_requirements(): no uv.lock (MLflow would restore the whole project with
    # `uv sync`, agent SDK and web server included).
    os.environ["MLFLOW_LOG_UV_FILES"] = "false"
    with registry_io.mlflow_session("harness", experiment=s.decisioning["experiment_path"]):
        with mlflow.start_run(run_name=f"decision-{versions['build_id']}", tags={"lau_kind": "decision_build"}) as run:
            mlflow.log_dict(versions, "versions.json")
            info = mlflow.pyfunc.log_model(
                name="decision_model",
                python_model=model,
                signature=signature(),
                code_paths=[str(ROOT / "src" / "lau")],
                pip_requirements=pip_requirements(),
            )
        run_id = run.info.run_id
    name = decision_model_name()
    tags = {k: "" if v is None else str(v) for k, v in versions.items()} | {"lau_kind": "decision_model"}
    with registry_io.mlflow_session("promoter") as c:
        try:
            c.create_registered_model(name, tags={"project": "lau"})
        except Exception:  # noqa: BLE001, S110 - already exists
            pass
        mv = mlflow.register_model(info.model_uri, name, tags=tags)
        for k, v in tags.items():
            c.set_model_version_tag(name, mv.version, k, v)
        c.set_registered_model_alias(name, LIVE_ALIAS, mv.version)
    row = {
        "build_id": versions["build_id"],
        "decision_model_version": str(mv.version),
        "run_id": run_id,
        "versions_json": json.dumps(versions, sort_keys=True),
        "built_at": datetime.now(UTC),
        "built_by": by or getpass.getuser(),
    }
    get_store("harness").write_df("ops", "decision_builds", pd.DataFrame([row]), mode="append")
    serving = f"v{versions['model_version']}" if versions["model_version"] else "legacy policy"
    shadow = f", shadow v{versions['shadow_model_version']}" if versions["shadow_model_version"] else ""
    log(f"decision model v{mv.version} is live: {serving}{shadow}, policy {versions['policy_version']}")
    return {"version": str(mv.version), "build_id": versions["build_id"], "changed": True, "versions": versions}


def load_live():
    """The live DecisionModel object (the in-process transport decides with exactly what the endpoint serves)."""
    found = live()
    if found is None:
        return None
    import mlflow

    with registry_io.mlflow_session("harness"):
        return mlflow.pyfunc.load_model(f"models:/{decision_model_name()}@{LIVE_ALIAS}").unwrap_python_model()


# ---- Model Serving ---------------------------------------------------------------------------------------------------
def _endpoint_cfg() -> dict:
    return get_settings().decisioning["endpoint"]


def _workspace(role: str):
    from databricks.sdk import WorkspaceClient

    from lau.credentials import databricks_config

    return WorkspaceClient(config=databricks_config(role))


def endpoint_state() -> dict:
    """{exists, ready, served_version, updating}; never raises (no endpoint on the local backend)."""
    if get_settings().project.backend == "local":
        return {"exists": False, "reason": "local backend: decisions run in process"}
    try:
        ep = _workspace("harness").serving_endpoints.get(_endpoint_cfg()["name"])
    except Exception as e:  # noqa: BLE001 - not created (or no permission to see it)
        return {"exists": False, "reason": f"{type(e).__name__}"}
    served = (ep.config.served_entities or []) if ep.config else []
    return {
        "exists": True,
        "ready": str(getattr(ep.state, "ready", "")).endswith("READY") and "NOT" not in str(ep.state.ready),
        "updating": str(getattr(ep.state, "config_update", "")).endswith("IN_PROGRESS"),
        "served_version": served[0].entity_version if served else None,
    }


def deploy(version: str | None = None, create: bool = False, log=print) -> dict:
    s = get_settings()
    if s.project.backend == "local":
        return {"deployed": False, "reason": "local backend: decisions run in process (no endpoint)"}
    from databricks.sdk.service.serving import (
        AiGatewayConfig,
        AiGatewayInferenceTableConfig,
        EndpointCoreConfigInput,
        ServedEntityInput,
    )

    found = live()
    version = version or (found[0] if found else None)
    if version is None:
        raise RuntimeError("no decision model is registered yet: run `lau decision build`")
    cfg = _endpoint_cfg()
    entity = ServedEntityInput(
        entity_name=decision_model_name(),
        entity_version=str(version),
        workload_size=cfg["workload_size"],
        scale_to_zero_enabled=bool(cfg["scale_to_zero"]),
    )
    state = endpoint_state()
    if not state["exists"]:
        if not create:
            return {
                "deployed": False,
                "reason": "the endpoint does not exist; creating it is compute: `lau decision deploy --create`",
            }
        w = _workspace("admin")
        log(f"creating endpoint {cfg['name']} ({cfg['workload_size']}, scale to zero) serving v{version}...")
        ep = w.serving_endpoints.create_and_wait(
            name=cfg["name"],
            config=EndpointCoreConfigInput(served_entities=[entity]),
            ai_gateway=AiGatewayConfig(
                inference_table_config=AiGatewayInferenceTableConfig(
                    catalog_name=s.catalog,
                    schema_name=s.schema("ops"),
                    table_name_prefix=cfg["inference_table_prefix"],
                    enabled=True,
                )
            ),
            timeout=timedelta(minutes=45),  # the first container build of a custom model takes a while
        )
        _endpoint_permissions(w, ep.id)
        return {"deployed": True, "created": True, "version": str(version)}
    if state["served_version"] == str(version):
        return {"deployed": True, "changed": False, "version": str(version)}
    log(f"updating endpoint {cfg['name']} to decision model v{version}...")
    _workspace("promoter").serving_endpoints.update_config_and_wait(
        name=cfg["name"], served_entities=[entity], timeout=timedelta(minutes=45)
    )
    return {"deployed": True, "changed": True, "version": str(version)}


def _endpoint_permissions(w, endpoint_id: str) -> None:
    from databricks.sdk.service.serving import ServingEndpointAccessControlRequest, ServingEndpointPermissionLevel

    sps = get_settings().state.service_principals
    levels = {
        "harness": ServingEndpointPermissionLevel.CAN_QUERY,  # synthetic traffic and release checks
        "promoter": ServingEndpointPermissionLevel.CAN_MANAGE,  # moves the endpoint to a new decision model version
        "ui": ServingEndpointPermissionLevel.CAN_VIEW,  # the console snapshot shows the endpoint's state
    }
    w.serving_endpoints.set_permissions(
        endpoint_id,
        access_control_list=[
            ServingEndpointAccessControlRequest(service_principal_name=sps[r]["application_id"], permission_level=lvl)
            for r, lvl in levels.items()
            if r in sps
        ],
    )


def publish(log=print) -> dict:
    """Build from the current approved state, then move the endpoint (if it exists) to the live version."""
    b = build(log=log)
    d = deploy(b["version"], create=False, log=log)
    return {"published": True, "build": b, "deploy": d}


def status() -> dict:
    """What decides right now, and whether the registry, the live build and the endpoint agree."""
    found = live()
    tags = found[1] if found else {}
    serving = registry_io.serving_model("harness")
    from lau.decision import rollout

    active = policies.active()
    ep = endpoint_state()
    gaps = []
    want_model = serving["model_version"] if serving else ""
    if found and tags.get("model_version", "") != want_model:
        gaps.append("the live build embeds a different serving model than the registry: run `lau decision build`")
    if found and active and tags.get("policy_version") != active[0]:
        gaps.append("the live build embeds a policy that is no longer active: run `lau decision build`")
    if found and tags.get("shadow_model_version", "") != (rollout.shadow_version() or ""):
        gaps.append("the live build's shadow model differs from the rollout in shadow: run `lau decision build`")
    if ep.get("exists") and found and ep.get("served_version") != found[0]:
        gaps.append(f"the endpoint serves v{ep.get('served_version')}, live is v{found[0]}: run `lau decision deploy`")
    return {
        "live_version": found[0] if found else None,
        "live": tags,
        "serving_model_version": want_model or None,
        "shadow_model_version": rollout.shadow_version(),
        "active_policy": active[0] if active else None,
        "endpoint": ep,
        "gaps": gaps,
    }
