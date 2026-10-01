"""A synthetic stand-in for the Census surname table: P(group | surname) for a small pool of surnames.

Synthetic traffic draws each applicant's surname from P(surname | group) ∝ P(group | surname) (uniform surname
frequencies), so a surname-based estimate of group membership (the BISG method without its geography term) can be
computed from the table and checked against the synthetic truth. Real use needs the Census surname file, counsel's
approval of the method, and geography from the applicant's address.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GROUPS = ("white", "black", "hispanic", "asian", "other")

# surname -> P(white, black, hispanic, asian, other); each row sums to 1
TABLE: dict[str, tuple[float, float, float, float, float]] = {
    "olson": (0.92, 0.02, 0.02, 0.01, 0.03),
    "schmidt": (0.91, 0.03, 0.02, 0.01, 0.03),
    "larsen": (0.93, 0.01, 0.02, 0.01, 0.03),
    "sullivan": (0.89, 0.05, 0.02, 0.01, 0.03),
    "mueller": (0.92, 0.02, 0.02, 0.01, 0.03),
    "smith": (0.70, 0.23, 0.02, 0.01, 0.04),
    "johnson": (0.61, 0.34, 0.02, 0.01, 0.02),
    "brown": (0.58, 0.35, 0.02, 0.01, 0.04),
    "davis": (0.62, 0.32, 0.02, 0.01, 0.03),
    "washington": (0.05, 0.89, 0.02, 0.01, 0.03),
    "jefferson": (0.14, 0.80, 0.02, 0.01, 0.03),
    "mosley": (0.25, 0.70, 0.02, 0.01, 0.02),
    "okafor": (0.03, 0.93, 0.01, 0.01, 0.02),
    "garcia": (0.05, 0.01, 0.92, 0.01, 0.01),
    "rodriguez": (0.05, 0.01, 0.93, 0.00, 0.01),
    "hernandez": (0.04, 0.01, 0.94, 0.00, 0.01),
    "silva": (0.20, 0.03, 0.70, 0.02, 0.05),
    "nguyen": (0.02, 0.00, 0.01, 0.95, 0.02),
    "kim": (0.02, 0.00, 0.01, 0.94, 0.03),
    "chen": (0.02, 0.00, 0.01, 0.95, 0.02),
    "patel": (0.03, 0.01, 0.01, 0.92, 0.03),
    "khan": (0.10, 0.08, 0.01, 0.60, 0.21),
    "lee": (0.40, 0.17, 0.01, 0.39, 0.03),
    "begay": (0.04, 0.01, 0.02, 0.01, 0.92),
    "yazzie": (0.03, 0.01, 0.02, 0.01, 0.93),
}
NAMES = np.array(list(TABLE))
P_GROUP_GIVEN_NAME = np.array([TABLE[n] for n in NAMES])  # (names, groups)


def draw(rng: np.random.Generator, groups: np.ndarray) -> np.ndarray:
    """A surname for each applicant, drawn from P(surname | group) ∝ P(group | surname)."""
    cols = {g: i for i, g in enumerate(GROUPS)}
    weights = P_GROUP_GIVEN_NAME / P_GROUP_GIVEN_NAME.sum(axis=0)  # column g: P(surname | g)
    out = np.empty(len(groups), dtype=object)
    for g in GROUPS:
        idx = np.where(groups == g)[0]
        if idx.size:
            out[idx] = rng.choice(NAMES, size=idx.size, p=weights[:, cols[g]])
    return out


def estimate(surnames: pd.Series) -> pd.DataFrame:
    """P(group | surname) per applicant; an unknown surname gets the population shares of the table."""
    prior = P_GROUP_GIVEN_NAME.mean(axis=0)
    index = {n: i for i, n in enumerate(NAMES)}
    rows = [P_GROUP_GIVEN_NAME[index[s]] if s in index else prior for s in surnames.astype(str).str.lower()]
    return pd.DataFrame(rows, columns=list(GROUPS), index=surnames.index)
