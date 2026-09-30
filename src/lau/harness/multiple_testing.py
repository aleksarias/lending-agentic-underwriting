"""Experiment-count tracking and the multiple-testing-aware promotion margin.

Every candidate evaluated against the validation split of a definition version is one "test". The required AUC
improvement over the reference grows with the number of tests already run on the SAME validation data:

    margin(n) = base_auc_margin + mt_penalty_k * sqrt(ln(1 + n))

n counts tests since the last reset (validation labels rebuilt for a new definition or data version).
This is a pragmatic alpha-spending-style heuristic (validation AUC noise roughly scales with sqrt(log m) for the max
of m correlated draws), not an exact correction; it is documented in docs/design-decisions.md. The counter is keyed
by definition_version, so it resets when the definition (and therefore the validation labels) changes.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pandas as pd


def required_margin(n_tests: int, cfg: dict) -> float:
    return float(cfg["base_auc_margin"] + cfg["mt_penalty_k"] * math.sqrt(math.log(1 + max(n_tests, 0))))


def n_tests(store, version: str) -> int:
    """Validation tests run since the last reset for this definition version.

    The harness_reference stage records a reset whenever validation labels are rebuilt (new definition OR new data
    version), because tests on the previous validation sample say nothing about the new one.
    """
    if not store.table_exists("ops", "experiment_counter"):
        return 0
    df = store.query(
        f"SELECT purpose, ts FROM {store.fq('ops', 'experiment_counter')} WHERE definition_version = '{version}'"
    )
    resets = df.loc[df["purpose"] == "reset", "ts"]
    tests = df[df["purpose"] == "validation_test"]
    if len(resets):
        tests = tests[tests["ts"] > resets.max()]
    return int(len(tests))


def record(store, version: str, candidate_ref: str, purpose: str = "validation_test") -> None:
    store.write_df(
        "ops",
        "experiment_counter",
        pd.DataFrame(
            [
                {
                    "definition_version": version,
                    "candidate_ref": candidate_ref,
                    "purpose": purpose,
                    "ts": datetime.now(UTC),
                }
            ]
        ),
        mode="append",
    )
