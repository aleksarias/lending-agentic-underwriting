"""Typed loader for config/benchmarks.yaml: frozen benchmark definitions, the reference score and the window policy.

The benchmarks are append-only yardsticks. Each is the base definition with only `delinquency_threshold_dpd`
overridden, so every registered model is judged against the same fixed outcomes whichever definition of default is
currently active. Nothing here reads the lake.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from lau.definition.hashing import definition_version
from lau.definition.schema import DefaultDefinition, definition_from_dict, load_definition
from lau.settings import CONFIG_DIR

REFERENCE_LABEL = "Legacy policy score"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BenchmarkSpec(_Strict):
    key: str
    dpd: int


class ReferenceSpec(_Strict):
    key: str
    column: str
    direction: Literal["higher_is_safer", "higher_is_riskier"] = "higher_is_safer"
    label: str = REFERENCE_LABEL


class WindowSpec(_Strict):
    policy: Literal["validation", "latest_matured_excluding_holdout"] = "validation"
    months: int = Field(5, ge=1)


class BootstrapSpec(_Strict):
    resamples: int = Field(400, ge=20)
    seed: int = 0
    level: float = Field(0.95, gt=0.0, lt=1.0)


class BenchmarkConfig(_Strict):
    base_definition: str
    benchmarks: list[BenchmarkSpec] = Field(min_length=1)
    primary: str
    reference: ReferenceSpec
    window: WindowSpec = WindowSpec()
    bootstrap: BootstrapSpec = BootstrapSpec()
    fixed_approval_rate: float = Field(0.70, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _check_keys(self) -> BenchmarkConfig:
        keys = [b.key for b in self.benchmarks]
        if len(set(keys)) != len(keys):
            raise ValueError(f"duplicate benchmark keys: {keys}")
        if self.primary not in keys:
            raise ValueError(f"primary benchmark {self.primary!r} is not one of {keys}")
        return self


@dataclass(frozen=True)
class Benchmark:
    """A resolved benchmark: key, DPD threshold, and the full definition + its content hash."""

    key: str
    dpd: int
    definition: DefaultDefinition
    version: str


def load_benchmark_config(path: str | Path | None = None) -> BenchmarkConfig:
    p = Path(path) if path else CONFIG_DIR / "benchmarks.yaml"
    with open(p) as fh:
        return BenchmarkConfig(**(yaml.safe_load(fh) or {}))


def resolve_benchmarks(cfg: BenchmarkConfig, config_dir: Path | None = None) -> list[Benchmark]:
    """Benchmark definitions = base definition (path relative to the config dir) + the benchmark's DPD threshold."""
    base = load_definition((config_dir or CONFIG_DIR) / cfg.base_definition).model_dump(mode="json")
    out = []
    for b in cfg.benchmarks:
        defn = definition_from_dict({**base, "delinquency_threshold_dpd": b.dpd})
        out.append(Benchmark(b.key, b.dpd, defn, definition_version(defn)))
    return out
