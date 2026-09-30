"""THE ONLY place that turns raw loan performance into a default label.

No other module may compute, cache or approximate "default". Everything downstream reads labels produced here
(through lau.definition.labels_io), tagged with the `definition_version` that produced them.

Inputs (one row per loan-month, from raw.performance): loan_id, application_id, mob, status, dpd, balance,
past_due_amount, scheduled_payment, payment_amount, *_flag columns.
Loan attributes (from curated/raw applications): loan_id, application_id, origination_month, decision_ts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lau.definition.hashing import definition_version
from lau.definition.schema import DefaultDefinition
from lau.definition.sql_predicate import PERFORMANCE_COLUMNS, evaluate_expression

LABEL_COLUMNS = [
    "definition_version",
    "loan_id",
    "application_id",
    "origination_month",
    "decision_ts",
    "label",
    "is_excluded",
    "exclusion_reason",
    "is_censored",
    "default_mob",
    "default_trigger",
    "months_available",
]

# Priority when several exclusions apply to one loan.
_EXCLUSION_ORDER = ["fraud_confirmed", "deceased", "early_payoff"]


def months_available(origination_month: pd.Series, as_of_month: str) -> pd.Series:
    as_of = pd.Period(as_of_month, "M")
    return origination_month.map(lambda m: (as_of - pd.Period(m, "M")).n).astype(int)


def _first_mob(mask: pd.Series, perf: pd.DataFrame) -> pd.Series:
    """Earliest mob per loan where mask is True (NaN if never)."""
    return perf.loc[mask, ["loan_id", "mob"]].groupby("loan_id")["mob"].min()


def _cured_after_delinquency(window: pd.DataFrame, last_hit_mob: pd.Series, cure_months_required: int) -> pd.Series:
    """Decide which delinquency-only defaults are "cured" (used only when cure_handling.mode == cured_not_default).

    Args:
        window: performance rows restricted to mob <= observation_window_months, sorted by (loan_id, mob).
            Columns include loan_id, mob, dpd, status, forbearance_flag.
        last_hit_mob: Series indexed by loan_id -> the LAST mob at which the loan met the (material)
            delinquency threshold. Only loans whose default trigger is delinquency appear here.
        cure_months_required: consecutive "good" months needed after the hit.

    Returns:
        bool Series indexed by loan_id (same index as last_hit_mob): True => treat as cured (not a default).
    """
    # TODO(human): implement the cure rule.
    raise NotImplementedError("cure rule not implemented yet")


def build_labels(
    perf: pd.DataFrame,
    loans: pd.DataFrame,
    defn: DefaultDefinition,
    as_of_month: str,
) -> pd.DataFrame:
    version = definition_version(defn)
    W = int(defn.observation_window_months)
    loans = loans.drop_duplicates("loan_id").set_index("loan_id")
    avail = months_available(loans["origination_month"], as_of_month)

    perf = perf.sort_values(["loan_id", "mob"])
    window = perf[perf["mob"] <= W]

    # ---- delinquency events (material only) -----------------------------------------------------------
    material = window["past_due_amount"] >= defn.balance_materiality_threshold
    dlq_hit = (window["dpd"] >= defn.delinquency_threshold_dpd) & material
    if defn.delinquency_timing == "ever":
        dlq_mob = _first_mob(dlq_hit, window)
    else:  # end_of_window: state on the last observed row within the window (terminal rows carry forward)
        last = window.groupby("loan_id").tail(1)
        last_hit = (last["dpd"] >= defn.delinquency_threshold_dpd) & (
            last["past_due_amount"] >= defn.balance_materiality_threshold
        )
        # A loan still running must be observed at exactly mob == W for an end-of-window reading.
        terminal = last["status"].isin(["charged_off", "bankrupt", "settled", "fraud", "deceased", "paid_off"])
        ok = last_hit & ((last["mob"] == W) | terminal)
        dlq_mob = last.loc[ok].set_index("loan_id")["mob"]

    triggers: dict[str, pd.Series] = {"delinquency": dlq_mob}
    if defn.include_charge_off:
        triggers["charge_off"] = _first_mob(window["charge_off_flag"] == 1, window)
    if defn.include_bankruptcy:
        triggers["bankruptcy"] = _first_mob(window["bankruptcy_flag"] == 1, window)
    if defn.include_settlement:
        triggers["settlement"] = _first_mob(window["settlement_flag"] == 1, window)
    if defn.include_forbearance_as_default:
        triggers["forbearance"] = _first_mob(window["forbearance_flag"] == 1, window)
    if defn.custom_sql_predicate:
        hit = evaluate_expression(window, defn.custom_sql_predicate, PERFORMANCE_COLUMNS).fillna(False).astype(bool)
        triggers["custom_predicate"] = _first_mob(hit, window)

    trig = pd.DataFrame(triggers).reindex(loans.index)

    # ---- cure handling (delinquency-only defaults) --------------------------------------------------
    if defn.cure_handling.mode == "cured_not_default" and trig["delinquency"].notna().any():
        others = trig.drop(columns=["delinquency"]).notna().any(axis=1)
        dlq_only = trig["delinquency"].notna() & ~others
        last_hit_mob = window.loc[dlq_hit, ["loan_id", "mob"]].groupby("loan_id")["mob"].max()
        last_hit_mob = last_hit_mob.reindex(trig.index[dlq_only]).dropna()
        if len(last_hit_mob):
            cured = _cured_after_delinquency(window, last_hit_mob, defn.cure_handling.cure_months_required)
            cured_ids = cured[cured].index
            trig.loc[trig.index.isin(cured_ids), "delinquency"] = np.nan

    default_mob = trig.min(axis=1)
    # Trigger = column holding the earliest event (ties resolved by column order above). pandas' idxmin raises on
    # all-NA rows, so fill with a sentinel first.
    default_trigger = trig.fillna(np.inf).idxmin(axis=1).where(default_mob.notna())
    is_default = default_mob.notna()

    # ---- exclusions -------------------------------------------------------------------------------------
    reasons = pd.Series(pd.NA, index=loans.index, dtype=object)
    ever = perf.groupby("loan_id")
    if "fraud_confirmed" in defn.exclusions:
        fraud_ids = ever["fraud_flag"].max()
        reasons = reasons.mask(reasons.isna() & fraud_ids.reindex(loans.index).eq(1), "fraud_confirmed")
    if "deceased" in defn.exclusions:
        dec_ids = window.groupby("loan_id")["deceased_flag"].max()
        reasons = reasons.mask(reasons.isna() & dec_ids.reindex(loans.index).eq(1), "deceased")
    if "early_payoff" in defn.exclusions:
        ep = perf[(perf["payoff_flag"] == 1) & (perf["mob"] <= defn.early_payoff_within_months)]["loan_id"].unique()
        reasons = reasons.mask(reasons.isna() & loans.index.isin(ep), "early_payoff")

    # ---- maturity / seasoning ------------------------------------------------------------------------
    unseasoned = avail < defn.min_seasoning_months
    immature = avail < W
    reasons = reasons.mask(reasons.isna() & unseasoned, "unseasoned")
    is_censored = pd.Series(False, index=loans.index)
    if defn.maturity_rule == "exclude":
        reasons = reasons.mask(reasons.isna() & immature, "immature")
    else:
        is_censored = immature & reasons.isna()

    no_perf = ~loans.index.isin(perf["loan_id"].unique())
    reasons = reasons.mask(reasons.isna() & no_perf & (avail > 0), "no_performance")
    reasons = reasons.mask(reasons.isna() & (avail <= 0), "unseasoned")

    is_excluded = reasons.notna()
    label = pd.Series(is_default.astype("Int64"), index=loans.index)
    label[is_excluded] = pd.NA

    out = pd.DataFrame(
        {
            "definition_version": version,
            "loan_id": loans.index,
            "application_id": loans["application_id"].to_numpy(),
            "origination_month": loans["origination_month"].to_numpy(),
            "decision_ts": pd.to_datetime(loans["decision_ts"]).to_numpy(),
            "label": label.to_numpy(),
            "is_excluded": is_excluded.to_numpy(),
            "exclusion_reason": reasons.astype(object).where(is_excluded, None).to_numpy(),
            "is_censored": is_censored.to_numpy(),
            "default_mob": default_mob.where(~is_excluded).to_numpy(),
            "default_trigger": default_trigger.where(~is_excluded).astype(object).to_numpy(),
            "months_available": avail.to_numpy(),
        }
    )
    return out[LABEL_COLUMNS].reset_index(drop=True)


def label_summary(labels: pd.DataFrame) -> dict:
    elig = labels[~labels["is_excluded"]]
    uncensored = elig[~elig["is_censored"]]
    return {
        "n_loans": int(len(labels)),
        "n_eligible": int(len(elig)),
        "n_uncensored": int(len(uncensored)),
        "n_censored": int(elig["is_censored"].sum()),
        "n_default": int(uncensored["label"].sum()) if len(uncensored) else 0,
        "default_rate": float(uncensored["label"].mean()) if len(uncensored) else float("nan"),
        "exclusions": labels["exclusion_reason"].value_counts().to_dict(),
        "triggers": elig["default_trigger"].value_counts().to_dict(),
    }


def early_indicator(perf: pd.DataFrame, dpd: int, mob: int) -> pd.Series:
    """Monitoring outcome (NOT a default label): loan reached `dpd`+ by month-on-book `mob`. Indexed by loan_id."""
    w = perf[perf["mob"] <= mob]
    return (w.groupby("loan_id")["dpd"].max() >= dpd).astype(int)
