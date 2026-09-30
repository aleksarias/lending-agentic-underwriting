"""The ONLY sanctioned way to read labels. Enforces the definition-version contract.

* Every read names the `definition_version` it expects and the consumer (stage/component) reading it.
* Reads of a version other than the active one fail unless the caller explicitly opts in (`allow_inactive`),
  which only the side-by-side `compare` flow does.
* Every returned row is verified to carry the requested version.
* Every read is recorded in READ_LOG so tests can prove no stage read an untagged/inactive label.
* Agents (role 'agent') see TRAIN labels only (via the `labels.labels_active` view). Validation labels are used
  only inside the harness, where every use is counted for the multiple-testing margin.
* Out-of-time holdout labels are NOT served here; see lau.harness.holdout (promotion-time only).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from lau.definition.registry import active_version
from lau.store import Store


class LabelVersionError(RuntimeError):
    pass


@dataclass(frozen=True)
class LabelRead:
    consumer: str
    requested_version: str
    returned_versions: tuple[str, ...]
    active_version: str | None
    allow_inactive: bool


READ_LOG: list[LabelRead] = []

DEV_SPLITS = ("train", "validation")


def _agent_visible_version(store: Store) -> str | None:
    """Agents have no grant on ops; the active version for them is whatever the granted view is filtered to."""
    df = store.query(f"SELECT DISTINCT definition_version FROM {store.fq('labels', 'labels_active')}")
    return None if df.empty else str(df["definition_version"].iloc[0])


def read_labels(
    store: Store,
    version: str,
    consumer: str,
    splits: tuple[str, ...] = DEV_SPLITS,
    allow_inactive: bool = False,
) -> pd.DataFrame:
    """Eligible, uncensored, labelled dev-period loans with their split, for `version`."""
    if not version:
        raise LabelVersionError(f"{consumer}: a definition_version is required to read labels")
    bad = set(splits) - set(DEV_SPLITS)
    if bad:
        raise LabelVersionError(f"{consumer}: split(s) {bad} are not served here (holdout is promotion-only)")
    active = _agent_visible_version(store) if store.role == "agent" else active_version(store)
    if version != active and not allow_inactive:
        raise LabelVersionError(
            f"{consumer}: requested labels for {version} but the active definition is {active}; "
            "only `default-definition compare` may read inactive versions"
        )

    split_list = ", ".join(f"'{s}'" for s in splits)
    if store.role == "agent":
        if version != active:
            raise LabelVersionError("agents may only read the active definition's labels")
        if set(splits) != {"train"}:
            raise LabelVersionError("agents see train labels only; validation feedback comes via the harness")
        sql = f"SELECT * FROM {store.fq('labels', 'labels_active')} WHERE split IN ({split_list})"
    else:
        sql = (
            f"SELECT l.definition_version, l.loan_id, l.application_id, l.origination_month, l.decision_ts, "
            f"l.label, s.split, s.es_tail FROM {store.fq('labels', 'labels_all')} l "
            f"JOIN {store.fq('labels', 'splits')} s ON l.loan_id = s.loan_id "
            f"AND l.definition_version = s.definition_version "
            f"WHERE l.definition_version = '{version}' AND s.split IN ({split_list}) "
            f"AND NOT l.is_excluded AND NOT l.is_censored"
        )
    df = store.query(sql)
    returned = tuple(sorted(df["definition_version"].astype(str).unique())) if len(df) else ()
    READ_LOG.append(LabelRead(consumer, version, returned, active, allow_inactive))
    if returned and returned != (version,):
        raise LabelVersionError(f"{consumer}: label rows tagged {returned} but requested {version}")
    df["label"] = df["label"].astype(int)
    return df


def read_all_labels_for_version(
    store: Store, version: str, consumer: str, allow_inactive: bool = False
) -> pd.DataFrame:
    """Full label table (incl. excluded/censored rows) for pipeline stages running as harness/admin."""
    active = active_version(store)
    if version != active and not allow_inactive:
        raise LabelVersionError(f"{consumer}: {version} is not the active definition ({active})")
    df = store.query(f"SELECT * FROM {store.fq('labels', 'labels_all')} WHERE definition_version = '{version}'")
    returned = tuple(sorted(df["definition_version"].astype(str).unique())) if len(df) else ()
    READ_LOG.append(LabelRead(consumer, version, returned, active, allow_inactive))
    if returned and returned != (version,):
        raise LabelVersionError(f"{consumer}: label rows tagged {returned} but requested {version}")
    return df
