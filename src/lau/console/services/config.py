"""Configuration the console shows or derives from: YAML files, budgets, thresholds and the definition YAML hash."""

from __future__ import annotations

import yaml

from lau.settings import CONFIG_DIR, get_settings

PIPELINE_ROLES = ["planner", "profiler", "feature", "modeling", "redteam", "compliance", "curator"]


def budgets() -> dict:
    return get_settings().budgets


def thresholds() -> dict:
    return get_settings().thresholds


def protected() -> dict:
    return get_settings().protected


def model_config() -> dict:
    return get_settings().models


def cycle_caps() -> dict:
    return budgets().get("cycle", {})


def agent_caps(role: str) -> dict:
    caps = budgets().get("agents", {}).get(role, {})
    return {
        "max_turns": int(caps.get("max_turns", 0)),
        "max_budget_usd": float(caps.get("max_budget_usd", 0.0)),
        "timeout_min": int(caps.get("timeout_min", 0)),
    }


def yaml_file(name: str) -> dict:
    """A config YAML by file name (relative to the config dir); {} when missing or unreadable."""
    path = CONFIG_DIR / name
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def benchmarks_config() -> dict:
    return yaml_file("benchmarks.yaml")


def primary_benchmark_key() -> str | None:
    return benchmarks_config().get("primary")


def fixed_approval_rate() -> float:
    cfg = benchmarks_config()
    return float(cfg.get("fixed_approval_rate") or thresholds().get("fairness", {}).get("approval_rate", 0.7))


def yaml_definition_version() -> str | None:
    """Content hash of config/default_definition.yaml, or None if it cannot be loaded."""
    from lau.definition.hashing import definition_version
    from lau.definition.schema import load_definition

    try:
        return definition_version(load_definition(CONFIG_DIR / "default_definition.yaml"))
    except Exception:  # noqa: BLE001 - a broken YAML must not break the console
        return None
