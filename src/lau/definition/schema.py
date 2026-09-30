"""Typed, validated default definition. Semantic fields are hashed into `definition_version`; `metadata` is not."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from lau.definition.sql_predicate import normalize_predicate

ExclusionReason = Literal["fraud_confirmed", "early_payoff", "deceased"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Metadata(_Frozen):
    name: str = "unnamed"
    description: str = ""
    owner: str = ""


class CureHandling(_Frozen):
    mode: Literal["count_if_ever", "cured_not_default"] = "count_if_ever"
    cure_months_required: int = Field(3, ge=1, le=24)


class DefaultDefinition(_Frozen):
    metadata: Metadata = Metadata()

    delinquency_threshold_dpd: int = Field(..., ge=30, le=180, multiple_of=30)
    delinquency_timing: Literal["ever", "end_of_window"] = "ever"
    observation_window_months: int = Field(..., ge=1, le=60)
    min_seasoning_months: int = Field(0, ge=0, le=60)
    maturity_rule: Literal["exclude", "censor"] = "exclude"
    include_charge_off: bool = True
    include_bankruptcy: bool = True
    include_settlement: bool = True
    include_forbearance_as_default: bool = False
    cure_handling: CureHandling = CureHandling()
    exclusions: tuple[ExclusionReason, ...] = ()
    early_payoff_within_months: int = Field(3, ge=1, le=60)
    balance_materiality_threshold: float = Field(0.0, ge=0.0)
    custom_sql_predicate: str | None = None

    @field_validator("exclusions", mode="before")
    @classmethod
    def _norm_exclusions(cls, v):
        return tuple(sorted(set(v or ())))

    @field_validator("custom_sql_predicate", mode="before")
    @classmethod
    def _norm_predicate(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return normalize_predicate(v)  # validates against the sandbox; raises ValueError if unsafe

    @field_validator("balance_materiality_threshold", mode="before")
    @classmethod
    def _norm_money(cls, v):
        return round(float(v), 2)

    def semantic_dict(self) -> dict:
        """Canonical dict of hashed fields (metadata excluded)."""
        d = self.model_dump(mode="json", exclude={"metadata"})
        d["exclusions"] = sorted(d["exclusions"])
        return d


SEMANTIC_FIELDS = [f for f in DefaultDefinition.model_fields if f != "metadata"]


def load_definition(path: str | Path) -> DefaultDefinition:
    with open(path) as fh:
        return DefaultDefinition(**(yaml.safe_load(fh) or {}))


def definition_from_dict(d: dict) -> DefaultDefinition:
    return DefaultDefinition(**d)
