"""MLflow tracking + model registry, per role, for both backends.

Databricks: tracking "databricks", registry "databricks-uc"; credentials injected per role via
lau.credentials.role_env (MLflow reads env). Models:
  <catalog>.<experiments>.pd_candidates  - every challenger (registered by the agent identity)
  <catalog>.<production>.pd_model        - promoted champions only (registered by the promoter identity)
Local: sqlite tracking/registry under the local lake; same model names without the catalog prefix.

Aliases (per definition version, so champions of different definitions are never confused):
  champion_<v8>   - approved champion for that definition version (production model)
  challenger_<v8> - candidate currently proposed for promotion under that definition (candidate model)
  champion        - the model actually SERVING decisions (may belong to a superseded definition)
Every run and model version carries the tag `definition_version`.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow  # noqa: E402
import mlflow.pyfunc  # noqa: E402
import pandas as pd  # noqa: E402
from mlflow import MlflowClient  # noqa: E402

from lau.definition.hashing import short  # noqa: E402
from lau.settings import ROOT, get_settings  # noqa: E402

SERVING_ALIAS = "champion"


class DefinitionMismatchError(RuntimeError):
    """Raised when models from different definition versions would be compared or promoted together."""


def champion_alias(version: str) -> str:
    return f"champion_{short(version)}"


def challenger_alias(version: str) -> str:
    return f"challenger_{short(version)}"


def candidate_model_name() -> str:
    s = get_settings()
    n = s.project.mlflow.candidate_model
    return n if s.project.backend == "local" else s.fq("experiments", n)


def production_model_name() -> str:
    s = get_settings()
    n = s.project.mlflow.production_model
    return n if s.project.backend == "local" else s.fq("production", n)


class PDModelPyfunc(mlflow.pyfunc.PythonModel):
    def __init__(self, pd_model=None) -> None:
        self.pd_model = pd_model

    def predict(self, context, model_input: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
        return pd.DataFrame({"pd": self.pd_model.predict_pd(model_input)})


@contextlib.contextmanager
def mlflow_session(role: str, experiment: str | None = None) -> Iterator[MlflowClient]:
    """MLflow clients as `role`. `experiment` overrides the agents' experiment (decision builds use their own)."""
    s = get_settings()
    exp_name = experiment or s.project.mlflow.experiment_path
    if s.project.backend == "local":
        lake = s.local_lake
        uri = f"sqlite:///{lake / 'mlflow.db'}"
        mlflow.set_tracking_uri(uri)
        mlflow.set_registry_uri(uri)
        if mlflow.get_experiment_by_name(exp_name) is None:
            mlflow.create_experiment(exp_name, artifact_location=(lake / "mlartifacts").as_uri())
        mlflow.set_experiment(exp_name)
        yield MlflowClient(tracking_uri=uri, registry_uri=uri)
        return
    from lau.credentials import role_env

    with role_env(role):
        mlflow.set_tracking_uri("databricks")
        mlflow.set_registry_uri("databricks-uc")
        mlflow.set_experiment(exp_name)
        yield MlflowClient(tracking_uri="databricks", registry_uri="databricks-uc")


def log_candidate(
    model,
    metrics: dict[str, float],
    tags: dict[str, str],
    sample: pd.DataFrame,
    role: str = "agent",
    run_name: str | None = None,
) -> tuple[str, str]:
    """Log + register a trained PDModel as a candidate. Returns (run_id, model_version)."""
    from mlflow.models import infer_signature

    tags = {
        **tags,
        "definition_version": model.definition_version,
        "model_type": model.model_type,
        "lau_kind": "candidate",
    }
    inp = sample[model.raw_inputs].head(20).copy()  # engineered features are derived inside the model
    out = pd.DataFrame({"pd": model.predict_pd(inp)})
    with mlflow_session(role) as client, mlflow.start_run(run_name=run_name, tags=tags) as run:
        mlflow.log_params({f"p_{k}": v for k, v in model.params.items()})
        mlflow.log_param("n_features", len(model.features))
        mlflow.log_dict(model.describe(), "model_description.json")
        mlflow.log_metrics({k: float(v) for k, v in metrics.items() if v == v})
        info = mlflow.pyfunc.log_model(
            name="model",
            python_model=PDModelPyfunc(model),
            signature=infer_signature(inp, out),
            code_paths=[str(ROOT / "src" / "lau")],
            pip_requirements=_pip_reqs(),
        )
        mv = mlflow.register_model(info.model_uri, candidate_model_name(), tags=tags)
        for k, v in tags.items():
            client.set_model_version_tag(candidate_model_name(), mv.version, k, v)
        return run.info.run_id, str(mv.version)


def _pip_reqs() -> list[str]:
    import lightgbm
    import sklearn
    import xgboost

    return [
        f"lightgbm=={lightgbm.__version__}",
        f"xgboost=={xgboost.__version__}",
        f"scikit-learn=={sklearn.__version__}",
        "pandas",
        "numpy",
        "duckdb",
        "sqlglot",
    ]


def load_pd_model(model_uri: str, role: str):
    with mlflow_session(role):
        return mlflow.pyfunc.load_model(model_uri).unwrap_python_model().pd_model


def candidate_uri(version: str) -> str:
    return f"models:/{candidate_model_name()}/{version}"


def version_tags(model_name: str, version: str, role: str) -> dict[str, str]:
    with mlflow_session(role) as c:
        return dict(c.get_model_version(model_name, version).tags)


def alias_version(model_name: str, alias: str, role: str) -> tuple[str, dict[str, str]] | None:
    with mlflow_session(role) as c:
        try:
            mv = c.get_model_version_by_alias(model_name, alias)
        except Exception:  # noqa: BLE001 - alias or model not found
            return None
        return str(mv.version), dict(mv.tags)


def champion_for(version: str, role: str = "harness"):
    """(model_version, PDModel) of the champion OF THIS DEFINITION VERSION, or None. Never crosses versions."""
    found = alias_version(production_model_name(), champion_alias(version), role)
    if found is None:
        return None
    mv, tags = found
    if tags.get("definition_version") != version:
        raise DefinitionMismatchError(
            f"alias {champion_alias(version)} points at a model tagged {tags.get('definition_version')}"
        )
    model = load_pd_model(f"models:/{production_model_name()}/{mv}", role)
    if model.definition_version != version:
        raise DefinitionMismatchError("champion artifact definition_version mismatch")
    return mv, model


def serving_model(role: str = "harness") -> dict | None:
    found = alias_version(production_model_name(), SERVING_ALIAS, role)
    if found is None:
        return None
    mv, tags = found
    return {"model_version": mv, **tags}


def save_local_artifact(obj: Any, name: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix="lau_"))
    p = d / name
    if isinstance(obj, str):
        p.write_text(obj)
    else:
        import json

        p.write_text(json.dumps(obj, indent=2, default=str))
    return p
