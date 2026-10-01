"""Snapshot of the model registry (candidate + production models) into `ops.model_registry`.

The console reads only `ops`, never MLflow, so the registry is mirrored here on every evidence run. The same
enumeration feeds the benchmark ledger (which versions to score) and the verdict (which version is serving).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import pandas as pd

from lau.modeling import registry_io

CHAMPION_ROLES = {"baseline", "challenger", "retrained_champion_arch"}


@dataclass(frozen=True)
class RegistryVersion:
    """One version of a registered model, as MLflow / Unity Catalog reports it."""

    model_name: str
    version: str
    registry: Literal["candidate", "production"]
    aliases: tuple[str, ...]
    tags: Mapping[str, str]
    created_at_ms: int | None
    run_id: str | None

    @property
    def key(self) -> str:
        return f"{self.model_name}/{self.version}"

    @property
    def uri(self) -> str:
        return f"models:/{self.model_name}/{self.version}"

    @property
    def definition_version(self) -> str | None:
        return self.tags.get("definition_version")

    @property
    def source_candidate_version(self) -> str | None:
        """For a production model: the candidate version it was copied from."""
        return self.tags.get("source_candidate_version")

    @property
    def created_at(self) -> datetime | None:
        return None if self.created_at_ms is None else datetime.fromtimestamp(self.created_at_ms / 1000, UTC)


def _is_missing(e: Exception) -> bool:
    msg = str(e).lower()
    return any(s in msg for s in ("not found", "does not exist", "resource_does_not_exist", "not_found"))


def list_versions() -> list[RegistryVersion]:
    """Every version of the candidate model, then of the production model (oldest first).

    `search_model_versions` does not populate aliases (neither the local registry nor UC does), so aliases come from
    the registered model's alias map.
    """
    out: list[RegistryVersion] = []
    with registry_io.mlflow_session("harness") as client:
        for registry, name in (
            ("candidate", registry_io.candidate_model_name()),
            ("production", registry_io.production_model_name()),
        ):
            try:
                versions = list(client.search_model_versions(f"name = '{name}'"))
                alias_map = dict(client.get_registered_model(name).aliases or {}) if versions else {}
            except Exception as e:  # noqa: BLE001 - a model nobody has registered yet is simply empty
                if not _is_missing(e):
                    raise
                versions, alias_map = [], {}
            by_version: dict[str, set[str]] = {}
            for alias, version in alias_map.items():
                by_version.setdefault(str(version), set()).add(str(alias))
            for mv in sorted(versions, key=lambda v: int(v.version)):
                if callable(getattr(mv, "tags", None)):
                    # Unity Catalog search results (ModelVersionSearch) carry no tags or aliases: fetch each version
                    mv = client.get_model_version(name, mv.version)
                aliases = by_version.get(str(mv.version), set()) | set(mv.aliases or ())
                out.append(
                    RegistryVersion(
                        model_name=name,
                        version=str(mv.version),
                        registry=registry,  # type: ignore[arg-type]
                        aliases=tuple(sorted(aliases)),
                        tags={str(k): str(v) for k, v in dict(mv.tags or {}).items()},
                        created_at_ms=int(mv.creation_timestamp) if mv.creation_timestamp else None,
                        run_id=mv.run_id or None,
                    )
                )
    return out


def status_of(v: RegistryVersion) -> str:
    """serving > champion > superseded > retired > challenger > baseline > candidate (first match wins)."""
    aliases, tags = set(v.aliases), v.tags
    if v.registry == "production":
        if registry_io.SERVING_ALIAS in aliases:
            return "serving"
        if any(a.startswith("champion_") for a in aliases):
            return "champion"
    if tags.get("superseded_by_definition_change") == "true":
        return "superseded"
    if tags.get("status") == "retired":
        return "retired"
    if v.registry == "candidate" and any(a.startswith("challenger_") for a in aliases):
        return "challenger"
    if tags.get("lau_role") == "baseline":
        return "baseline"
    return "candidate"


def kind_of(v: RegistryVersion) -> str:
    """Model kind from registry tags: champion (promoted), else the lau_role, else a plain candidate."""
    if v.registry == "production" or v.tags.get("lau_kind") == "champion":
        return "champion"
    role = v.tags.get("lau_role")
    return role if role in CHAMPION_ROLES else "candidate"


def label_of(v: RegistryVersion) -> str:
    return f"v{v.version}" if v.registry == "candidate" else f"prod v{v.version}"


def serving_version(versions: list[RegistryVersion]) -> RegistryVersion | None:
    return next((v for v in versions if v.registry == "production" and registry_io.SERVING_ALIAS in v.aliases), None)


def frame(versions: list[RegistryVersion], synced_at: datetime) -> pd.DataFrame:
    rows = [
        {
            "synced_at": synced_at,
            "model_name": v.model_name,
            "version": v.version,
            "aliases": ",".join(v.aliases),
            "tags_json": json.dumps(dict(sorted(v.tags.items()))),
            "definition_version": v.definition_version,
            "lau_kind": v.tags.get("lau_kind"),
            "lau_role": v.tags.get("lau_role"),
            "status": status_of(v),
            "run_id": v.run_id,
            "created_at": v.created_at,
            "source_candidate_version": v.source_candidate_version,
        }
        for v in versions
    ]
    return pd.DataFrame(rows)


def compute(ctx) -> pd.DataFrame:
    return frame(ctx.registry, ctx.computed_at)
