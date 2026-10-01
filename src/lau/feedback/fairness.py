"""Fairness on actual decisions: approval and decline rates by protected group, and adverse impact ratios.

Lenders generally may not collect race and ethnicity for non-mortgage credit, so groups are ESTIMATED. Here: a
surname-based estimate (the BISG method without its geography term, from a synthetic surname table; synthetic
geography is redrawn per generated month, so it cannot stand in for census composition). Each applicant counts
towards every group in proportion to its estimated probability. Because the data are synthetic, the true groups are
known (simulation.truth) and reported next to the estimate, which shows how far the estimate can be trusted. Age 62+
comes from the application (age is collected). Sex is not estimated: synthetic first names carry no signal.

Counsel must approve the estimation method and the thresholds before any real use.
"""

from __future__ import annotations

import pandas as pd

from lau.settings import get_settings

WINDOW_DAYS = 90


def _rates(decisions: pd.Series, weights: pd.Series) -> dict:
    w = float(weights.sum())
    if w <= 0:
        return {"n": 0.0, "approval_rate": None, "decline_rate": None}
    return {
        "n": round(w, 2),
        "approval_rate": float((weights * (decisions == "approve")).sum() / w),
        "decline_rate": float((weights * (decisions == "decline")).sum() / w),
    }


def _rows(attribute: str, method: str, decisions: pd.Series, weights: pd.DataFrame, reference: str, min_air: float):
    rows = {g: _rates(decisions, weights[g]) for g in weights.columns}
    ref = rows.get(reference, {}).get("approval_rate")
    out = []
    for g, r in rows.items():
        air = r["approval_rate"] / ref if ref and r["approval_rate"] is not None else None
        out.append(
            {
                "attribute": attribute,
                "group": str(g),
                "method": method,
                "reference_group": reference,
                **r,
                "air": air,
                "below_threshold": bool(air is not None and air < min_air and g != reference),
            }
        )
    return out


def compute(ctx) -> pd.DataFrame:
    """ops.decision_fairness over the last WINDOW_DAYS of decisions (test traffic excluded)."""
    from lau.evidence.context import EvidenceNotReadyError
    from lau.synth.surnames import estimate

    st = ctx.store
    if not (st.table_exists("ops", "decisions") and st.table_exists("simulation", "truth")):
        raise EvidenceNotReadyError("no decisions on synthetic traffic yet")
    t = st.fq("ops", "decisions")
    df = st.query(
        f"SELECT d.application_id, d.decision, s.surname, s.race_ethnicity, s.age FROM {t} d "
        f"JOIN {st.fq('simulation', 'truth')} s ON d.application_id = s.application_id "
        f"WHERE NOT d.is_test AND d.decided_at >= (SELECT max(decided_at) FROM {t}) - INTERVAL {WINDOW_DAYS} DAYS"
    ).drop_duplicates("application_id", keep="last")
    if df.empty:
        raise EvidenceNotReadyError("no decisions on synthetic traffic yet")
    prot = get_settings().protected["protected_classes"]
    min_air = float(get_settings().thresholds["fairness"]["min_air"])
    race_ref = prot["race_ethnicity"]["reference_group"]
    rows = _rows("race_ethnicity", "surname_estimate", df["decision"], estimate(df["surname"]), race_ref, min_air)
    truth = pd.get_dummies(df["race_ethnicity"]).astype(float)
    rows += _rows("race_ethnicity", "synthetic_truth", df["decision"], truth, race_ref, min_air)
    age = pd.get_dummies((df["age"] >= 62).map({True: "true", False: "false"})).astype(float)
    rows += _rows("age_62_plus", "application", df["decision"], age, prot["age_62_plus"]["reference_group"], min_air)
    out = pd.DataFrame(rows)
    out.insert(0, "n_decisions", len(df))
    out.insert(0, "window_days", WINDOW_DAYS)
    out.insert(0, "run_id", ctx.run_id)
    out.insert(0, "computed_at", ctx.computed_at)
    return out
