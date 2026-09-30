"""Test fixtures: an isolated local lake (DuckDB + sqlite MLflow) with small synthetic data.

Nothing here touches Databricks, the real LESSONS.md, the real .env, or reports/.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="lau_tests_"))
_CFG = _TMP / "config"
shutil.copytree(ROOT / "config", _CFG)
# Tests pin their own baseline definition (90 DPD) instead of whatever the operator currently has active.
shutil.copy(ROOT / "config" / "definitions" / "dpd90_ever_12m.yaml", _CFG / "default_definition.yaml")

# small, fast synthetic data
_synth = yaml.safe_load((_CFG / "synth.yaml").read_text())
_synth.update({"n_applications": 9000, "n_noise_numeric": 20, "n_new_applications": 800})
(_CFG / "synth.yaml").write_text(yaml.safe_dump(_synth))

os.environ.update(
    {
        "LAU_BACKEND": "local",
        "LAU_ENVIRONMENT": "dev",
        "LAU_CONFIG_DIR": str(_CFG),
        "LAU_LOCAL_LAKE": str(_TMP / "lake"),
        "LAU_STATE_DIR": str(_TMP / "state"),
        "LAU_LESSONS_FILE": str(_TMP / "LESSONS.md"),
        "LAU_REPORTS_DIR": str(_TMP / "reports"),
        "LAU_ENV_FILE": str(_TMP / ".env.test"),
        "MLFLOW_DISABLE_AGENT_HINT": "1",
    }
)
(_TMP / ".env.test").write_text("ANTHROPIC_API_KEY=placeholder-not-a-real-key\n")


def _fresh() -> None:
    from lau.settings import get_settings
    from lau.store import clear_store_cache, reset_local_connections

    get_settings.cache_clear()
    clear_store_cache()
    reset_local_connections()


@pytest.fixture(scope="session")
def cfg_dir() -> Path:
    return _CFG


@pytest.fixture(scope="session")
def lake():
    """Local lake with data generated and the default (90 DPD) definition applied."""
    import warnings

    warnings.filterwarnings("ignore")
    _fresh()
    from lau.governance.uc_layout import run_init
    from lau.pipeline import definition_ops as ops
    from lau.synth.ingest import gen_data

    run_init(log=lambda m: None)
    gen_data(log=lambda m: None)
    res = ops.apply(path=_CFG / "default_definition.yaml", confirm=lambda q: True, run_cycle=False, log=lambda m: None)
    return {"version": res["version"], "tmp": _TMP, "cfg": _CFG}


@pytest.fixture
def definition_yaml(tmp_path):
    """Write a modified copy of the default definition; returns a function(changes) -> path."""

    def _write(changes: dict) -> Path:
        d = yaml.safe_load((_CFG / "default_definition.yaml").read_text())
        for k, v in changes.items():
            d[k] = v
        p = tmp_path / f"def_{abs(hash(str(sorted(changes.items()))))}.yaml"
        p.write_text(yaml.safe_dump(d))
        return p

    return _write


@pytest.fixture(scope="session")
def synth_small():
    from lau.synth.generator import generate

    cfg = yaml.safe_load((_CFG / "synth.yaml").read_text())
    return generate(cfg, n_applications=6000)
