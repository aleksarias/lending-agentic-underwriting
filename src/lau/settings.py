"""Typed access to config/*.yaml and the generated workspace state (.lau/workspace_state.json).

No secrets live in any of these files. All credentials come from `.env` via lau.credentials.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(os.environ.get("LAU_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_DIR = Path(os.environ.get("LAU_CONFIG_DIR", ROOT / "config"))
STATE_DIR = Path(os.environ.get("LAU_STATE_DIR", ROOT / ".lau"))

ROLES = ("admin", "harness", "agent", "promoter")
Role = Literal["admin", "harness", "agent", "promoter"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SchemaNames(_Strict):
    raw: str
    curated: str
    labels: str
    feature_registry: str
    experiments: str
    holdout: str
    production: str
    ops: str
    simulation: str


class WarehouseCfg(_Strict):
    name: str
    cluster_size: str
    auto_stop_mins: int
    dbu_per_hour: float
    usd_per_dbu: float
    adopt_existing_if_quota: str | None = None


class PrincipalCfg(_Strict):
    sp_display_name: str | None = None


class MlflowCfg(_Strict):
    experiment_path: str
    candidate_model: str
    production_model: str


class ProjectConfig(_Strict):
    environment: Literal["dev", "prod"]
    backend: Literal["databricks", "local"]
    host: str
    catalog: str
    catalog_fallback: str
    schema_prefix_fallback: str
    schemas: SchemaNames
    warehouse: WarehouseCfg
    principals: dict[str, PrincipalCfg]
    mlflow: MlflowCfg
    local_lake_dir: str
    reports_dir: str
    lessons_file: str


class WorkspaceState(BaseModel):
    """IDs discovered/created by `lau init`. Not secret. Lives in .lau/ (gitignored, per-workspace)."""

    catalog: str | None = None
    schema_prefix: str = ""
    catalog_created_by_project: bool = False
    warehouse_id: str | None = None
    warehouse_created_by_project: bool = False
    warehouse_original_settings: dict | None = None  # set when an existing warehouse was adopted + resized
    service_principals: dict[str, dict[str, str]] = {}  # role -> {id, application_id, display_name}
    experiment_id: str | None = None
    decision_experiment_id: str | None = None
    job_ids: dict[str, str] = {}


def _load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name) as fh:
        return yaml.safe_load(fh) or {}


class Settings:
    def __init__(self) -> None:
        self.project = ProjectConfig(**_load_yaml("project.yaml"))
        backend = os.environ.get("LAU_BACKEND")
        if backend:
            self.project.backend = backend  # type: ignore[assignment]
        env = os.environ.get("LAU_ENVIRONMENT")
        if env:
            self.project.environment = env  # type: ignore[assignment]
        self.budgets = _load_yaml("budgets.yaml")
        self.models = _load_yaml("models.yaml")
        self.thresholds = _load_yaml("thresholds.yaml")
        self.protected = _load_yaml("protected_classes.yaml")
        self.synth = _load_yaml("synth.yaml")
        self.masking = _load_yaml("masking.yaml")
        self.decisioning = _load_yaml("decisioning.yaml")
        self.feedback = _load_yaml("feedback.yaml")
        self.readiness = _load_yaml("readiness.yaml")
        self.state = load_state()

    # ---- naming -------------------------------------------------------------------------------------
    @property
    def catalog(self) -> str:
        if self.project.backend == "local":
            return self.project.catalog
        return self.state.catalog or self.project.catalog

    @property
    def schema_prefix(self) -> str:
        return "" if self.project.backend == "local" else self.state.schema_prefix

    def schema(self, key: str) -> str:
        """Physical schema name for a logical schema key (e.g. 'holdout')."""
        return self.schema_prefix + getattr(self.project.schemas, key)

    def fq(self, key: str, table: str) -> str:
        return f"{self.catalog}.{self.schema(key)}.{table}"

    def schema_key_of(self, physical_schema: str) -> str | None:
        for key in SchemaNames.model_fields:
            if self.schema(key).lower() == physical_schema.lower():
                return key
        return None

    @property
    def local_lake(self) -> Path:
        p = Path(os.environ.get("LAU_LOCAL_LAKE", ROOT / self.project.local_lake_dir))
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def reports_dir(self) -> Path:
        p = Path(os.environ.get("LAU_REPORTS_DIR", ROOT / self.project.reports_dir))
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def lessons_path(self) -> Path:
        return Path(os.environ.get("LAU_LESSONS_FILE", ROOT / self.project.lessons_file))

    @property
    def masking_enabled(self) -> bool:
        flag = self.masking.get("enabled")
        if flag is None:
            return self.project.environment == "prod"
        return bool(flag)


def load_state() -> WorkspaceState:
    path = STATE_DIR / "workspace_state.json"
    if path.exists():
        return WorkspaceState(**json.loads(path.read_text()))
    return WorkspaceState()


def save_state(state: WorkspaceState) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "workspace_state.json").write_text(state.model_dump_json(indent=2))
    get_settings.cache_clear()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
