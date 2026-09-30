"""Out-of-time holdout access. Only `lau.harness.gate.promotion_gate` can obtain a HoldoutToken.

Three layers keep agents away from the holdout:
  1. UC grants: only the harness principal has any privilege on the `holdout` schema.
  2. The in-process ACL in every Store mirrors those grants (agent role -> AccessDeniedError).
  3. This module requires a token that only the promotion gate constructs, so even harness code paths used during
     ordinary evaluation cannot read the holdout by accident.
"""

from __future__ import annotations

import pandas as pd


class HoldoutAccessError(PermissionError):
    pass


class HoldoutToken:
    __slots__ = ("purpose", "candidate_ref")

    def __init__(self, _secret: object, purpose: str, candidate_ref: str) -> None:
        if _secret is not _GATE_SECRET:
            raise HoldoutAccessError("holdout tokens are issued only by the promotion gate")
        self.purpose = purpose
        self.candidate_ref = candidate_ref


_GATE_SECRET = object()


def _issue(purpose: str, candidate_ref: str) -> HoldoutToken:  # used by gate.py only
    return HoldoutToken(_GATE_SECRET, purpose, candidate_ref)


def read_holdout(store, version: str, token: HoldoutToken) -> pd.DataFrame:
    if not isinstance(token, HoldoutToken):
        raise HoldoutAccessError("a HoldoutToken from the promotion gate is required")
    if store.role != "harness":
        raise HoldoutAccessError(f"role '{store.role}' may not read the holdout")
    labels = store.query(
        f"SELECT application_id, label, origination_month FROM {store.fq('holdout', 'oot_labels')} "
        f"WHERE definition_version = '{version}'"
    )
    apps = store.query(f"SELECT * FROM {store.fq('curated', 'applications')} WHERE approved")
    df = apps.merge(labels[["application_id", "label"]], on="application_id", how="inner")
    df["label"] = df["label"].astype(int)
    return df


def holdout_months(store, version: str) -> tuple[str, str]:
    """OOT window boundaries (not labels) — safe metadata, used for through-the-door fairness at the gate."""
    df = store.query(
        f"SELECT oot_start, oot_end FROM {store.fq('labels', 'split_meta')} WHERE definition_version = '{version}'"
    )
    return str(df["oot_start"].iloc[0]), str(df["oot_end"].iloc[0])
