"""Console API: GET /api/settings (screen 20, reports and settings).

Configuration is shown read-only: changes go through git and the CLI, and every change is versioned in
ops.config_versions. Access checks are the latest `lau check-access` run.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from lau.console.services import benchmark, config, ops
from lau.console.util import api_router, unavailable

router = api_router()


def _benchmarks() -> list[dict]:
    run = benchmark.latest_run()
    measured = {d["key"]: d for d in benchmark.definitions_of(run)} if len(run) else {}
    out = []
    for b in config.benchmarks_config().get("benchmarks") or []:
        key = str(b.get("key"))
        out.append({"key": key, "dpd": int(b.get("dpd") or 0), "version": (measured.get(key) or {}).get("version", "")})
    return out


@router.get("/settings")
def settings() -> dict:
    return {
        "thresholds": config.thresholds(),
        "budgets": config.budgets(),
        "models": config.model_config(),
        "benchmarks": _benchmarks(),
        "protected_classes": config.protected(),
        "config_versions": ops.config_versions_latest(),
        "access_checks": ops.access_checks(),
        "notifications": unavailable(
            "Notifications (email or Slack on alerts, waiting decisions and finished cycles) are not configured.",
            ["Notification destination (Databricks SQL alert destinations or a Slack webhook)"],
        ),
    }
