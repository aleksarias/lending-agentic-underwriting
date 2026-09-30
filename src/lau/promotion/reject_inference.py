"""Reject inference / selection bias: NOT solved here — this is an explicit hook and a design helper.

Every label comes from loans the legacy policy approved. A challenger that would approve applicants the legacy
policy declined is evaluated only on the approved population, so its performance on the "swap-in" region is
unobserved. docs/reject-inference.md explains the limitation. This module offers:

  * RejectInferenceStrategy: interface for a future method (parcelling, augmentation, bureau-outcome proxies).
    The default NoRejectInference returns the approved-only training frame unchanged, and says so.
  * controlled_approval_design(): sizing for a small, time-boxed randomized approval experiment in a score band
    just below the cutoff — the only method that yields unbiased outcome data. It requires credit policy, compliance
    and loss-budget sign-off; nothing here executes it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import pandas as pd


class RejectInferenceStrategy(Protocol):
    name: str

    def augment(self, approved_train: pd.DataFrame, declined: pd.DataFrame) -> pd.DataFrame: ...


class NoRejectInference:
    name = "none"

    def augment(self, approved_train: pd.DataFrame, declined: pd.DataFrame) -> pd.DataFrame:
        return approved_train


@dataclass
class ControlledApprovalDesign:
    band: str
    monthly_declines_in_band: int
    approve_share: float
    months: int
    expected_bad_rate: float
    n_approved: int
    expected_defaults: int
    detectable_bad_rate_diff: float
    expected_loss_usd: float


def controlled_approval_design(
    monthly_declines_in_band: int,
    expected_bad_rate: float,
    avg_exposure_usd: float,
    lgd: float = 0.8,
    approve_share: float = 0.05,
    months: int = 6,
    band: str = "cutoff-to-cutoff+5pctl",
) -> ControlledApprovalDesign:
    n = int(monthly_declines_in_band * approve_share * months)
    se = math.sqrt(max(expected_bad_rate * (1 - expected_bad_rate), 1e-6) / max(n, 1))
    return ControlledApprovalDesign(
        band=band,
        monthly_declines_in_band=monthly_declines_in_band,
        approve_share=approve_share,
        months=months,
        expected_bad_rate=expected_bad_rate,
        n_approved=n,
        expected_defaults=int(n * expected_bad_rate),
        detectable_bad_rate_diff=2.8 * se,  # ~80% power, two-sided alpha=0.05
        expected_loss_usd=n * expected_bad_rate * avg_exposure_usd * lgd,
    )
