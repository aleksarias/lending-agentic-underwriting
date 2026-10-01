"""Model references and the synced model registry (ops.model_registry). The console never calls MLflow.

A ModelRef key is "legacy_score" for the frozen reference, else "<registered model name>/<version>". Candidates live in
the candidate model (`pd_candidates`), promoted champions in the production model (`pd_model`).
"""

from __future__ import annotations

import pandas as pd

from lau.console import deps
from lau.console.services import definitions as defs
from lau.console.util import boolean, col, loads, read_table, text, ttl_cache

REFERENCE_KEY = "legacy_score"
REFERENCE_LABEL = "Legacy policy score"
MODEL_KINDS = {"reference", "baseline", "challenger", "champion", "retrained_champion_arch", "candidate", "unknown"}
MODEL_STATUSES = {"serving", "champion", "challenger", "candidate", "baseline", "retired", "superseded"}
_REG_COLS = [
    "model_name",
    "version",
    "aliases",
    "tags",
    "definition_version",
    "lau_kind",
    "lau_role",
    "status",
    "run_id",
    "created_at",
    "source_candidate_version",
]


def names() -> tuple[str, str]:
    """(candidate model name, production model name) exactly as stored in the registry and in model routes.

    The registry mirror is the reference: a local console over tables exported from Databricks sees the full Unity
    Catalog names there, while the local settings would give the short names.
    """
    cand, prod = _configured_names()
    stored = set(registry()["model_name"]) if len(registry()) else set()

    def match(configured: str) -> str:
        short_name = configured.rsplit(".", 1)[-1]
        hits = sorted(n for n in stored if n == configured or n.rsplit(".", 1)[-1] == short_name)
        return hits[0] if len(hits) == 1 else configured

    return match(cand), match(prod)


def _configured_names() -> tuple[str, str]:
    try:
        from lau.modeling import registry_io

        return registry_io.candidate_model_name(), registry_io.production_model_name()
    except Exception:  # noqa: BLE001 - keep the console up even if MLflow cannot be imported
        from lau.settings import get_settings

        s = get_settings()
        cand, prod = s.project.mlflow.candidate_model, s.project.mlflow.production_model
        if s.project.backend == "local":
            return cand, prod
        return s.fq("experiments", cand), s.fq("production", prod)


def kind_of(lau_kind: str | None, lau_role: str | None) -> str:
    if lau_kind == "champion":
        return "champion"
    if lau_role in ("baseline", "challenger", "retrained_champion_arch"):
        return lau_role
    if lau_kind == "candidate":
        return "candidate"
    return "unknown"


def model_ref(
    name: str,
    version: str,
    kind: str = "unknown",
    definition_version: str | None = None,
    label: str | None = None,
) -> dict:
    return {
        "key": f"{name}/{version}",
        "name": name,
        "version": str(version),
        "label": label or f"v{version}",
        "kind": kind if kind in MODEL_KINDS else "unknown",
        "definition_version": definition_version,
    }


def reference_ref(label: str | None = None) -> dict:
    return {
        "key": REFERENCE_KEY,
        "name": REFERENCE_KEY,
        "version": "",
        "label": label or REFERENCE_LABEL,
        "kind": "reference",
        "definition_version": None,
    }


@ttl_cache(30)
def registry() -> pd.DataFrame:
    """ops.model_registry normalized (aliases -> list, tags -> dict); an empty frame if it has not been synced yet."""
    st = deps.ui_store()
    df = read_table(st, "ops", "model_registry", ts=["created_at", "synced_at"])
    if df.empty:
        return pd.DataFrame(columns=_REG_COLS)
    tags = [loads(x, {}) or {} for x in col(df, "tags_json")]
    out = pd.DataFrame(
        {
            "model_name": [str(x) for x in df["model_name"]],
            "version": [str(x) for x in df["version"]],
            "aliases": [
                [a.strip() for a in str(x).split(",") if a.strip()] if text(x) else [] for x in col(df, "aliases")
            ],
            "tags": tags,
            "definition_version": [
                text(x) or t.get("definition_version") for x, t in zip(col(df, "definition_version"), tags, strict=True)
            ],
            "lau_kind": [text(x) or t.get("lau_kind") for x, t in zip(col(df, "lau_kind"), tags, strict=True)],
            "lau_role": [text(x) or t.get("lau_role") for x, t in zip(col(df, "lau_role"), tags, strict=True)],
            "status": [text(x) for x in col(df, "status")],
            "run_id": [text(x) for x in col(df, "run_id")],
            "created_at": col(df, "created_at"),
            "source_candidate_version": [text(x) for x in col(df, "source_candidate_version")],
        }
    )
    return out.sort_values("created_at", ascending=False, na_position="last").reset_index(drop=True)


@ttl_cache(30)
def registry_index() -> dict[tuple[str, str], dict]:
    return {(r["model_name"], r["version"]): r for r in registry().to_dict("records")}


def registry_row(name: str, version: str) -> dict | None:
    return registry_index().get((name, str(version)))


def ref_from_row(row: dict) -> dict:
    return model_ref(
        row["model_name"],
        row["version"],
        kind_of(row.get("lau_kind"), row.get("lau_role")),
        row.get("definition_version"),
    )


def ref_for_candidate(candidate_ref: str) -> dict:
    """ModelRef for an evaluation ref such as "candidate:11" or "baseline:10" (works before any registry sync)."""
    prefix, _, version = candidate_ref.partition(":")
    cand_name, _ = names()
    if prefix in ("candidate", "baseline") and version:
        row = registry_row(cand_name, version)
        if row:
            return ref_from_row(row)
        return model_ref(cand_name, version, "baseline" if prefix == "baseline" else "candidate")
    return {
        "key": candidate_ref,
        "name": prefix or candidate_ref,
        "version": version,
        "label": candidate_ref,
        "kind": "unknown",
        "definition_version": None,
    }


def ref_from_key(
    key: str | None, label: str | None = None, kind: str | None = None, definition_version: str | None = None
) -> dict | None:
    """ModelRef from a "<name>/<version>" key (as used by benchmark and ledger tables)."""
    if not key:
        return None
    if key == REFERENCE_KEY:
        return reference_ref(label)
    name, _, version = key.rpartition("/")
    if not name:
        return model_ref(key, "", kind or "unknown", definition_version, label or key)
    row = registry_row(name, version)
    if row:
        ref = ref_from_row(row)
        if label:
            ref["label"] = label
        return ref
    return model_ref(name, version, kind or "unknown", definition_version, label)


@ttl_cache(10)
def promotions() -> pd.DataFrame:
    """production.promotions, newest first (the table exists only after the first promotion)."""
    df = read_table(deps.ui_store(), "production", "promotions", ts=["ts"])
    return df.sort_values("ts", ascending=False).reset_index(drop=True) if len(df) else df


def serving_model() -> dict | None:
    """The model making decisions: the production version holding the serving alias in the registry mirror.

    Promotions no longer switch serving (a champion starts in shadow; its rollout switches it), so the alias is the
    truth. Before the first registry sync, fall back to the newest promotion that switched serving.
    """
    from lau.modeling.registry_io import SERVING_ALIAS

    _, prod = names()
    reg = registry()
    mine = reg[reg["model_name"] == prod] if len(reg) else reg
    if len(mine):
        hit = mine[[SERVING_ALIAS in a for a in mine["aliases"]]]
        if hit.empty:
            return None  # synced and nothing holds the alias: the legacy policy decides
        r = hit.iloc[0]
        return model_ref(prod, str(r["version"]), "champion", text(r.get("definition_version")))
    df = promotions()
    if df.empty:
        return None
    serving = df[[boolean(x) is True for x in col(df, "serving", False)]]
    if serving.empty:
        return None
    r = serving.iloc[0]
    _, prod = names()
    version = str(r["production_model_version"])
    row = registry_row(prod, version)
    ref = model_ref(prod, version, "champion", text(r.get("definition_version")))
    if row and row.get("definition_version"):
        ref["definition_version"] = row["definition_version"]
    return ref


def serving_superseded(serving: dict | None) -> bool:
    active = defs.active_version()
    return bool(serving and active and serving.get("definition_version") not in (None, active))


def promotion_for_candidate(version: str) -> dict | None:
    """The promotion record that promoted candidate model version `version`, if any."""
    df = promotions()
    if df.empty:
        return None
    hit = df[df["candidate_model_version"].astype(str) == str(version)]
    return None if hit.empty else hit.iloc[0].to_dict()
