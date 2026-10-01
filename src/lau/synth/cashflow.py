"""Synthetic bank-statement (cash-flow) data: latent financial traits -> monthly transactions -> balances.

Design:
  * Latent per-applicant traits (income volatility, liquidity buffer, spending pressure, rent lateness, stated-income
    overstatement, gambling, remittances) are drawn in `latent_traits()` and some of them ALSO feed the default
    hazard in generator._applications (planted cash-flow signal). The transactions are noisy observations of them.
  * `simulate_transactions()` produces a compact but realistic statement: 8-14 rows per month (payroll/gig deposits,
    housing, utilities, other debt payments, groceries, discretionary, occasional gambling/remittance, NSF fees),
    ordered in time with a running balance. `days_before_decision` > 0 means before the credit decision.
  * For funded loans it also emits post-decision months, which must NEVER reach model features; the curate stage
    filters on days_before_decision >= 1 and a test proves it.

Calibration targets (approximate; documented in docs/synthetic-data.md, set in config/synth.yaml `cashflow:`):
  * share of households with volatile income ~25-35% (CFPB Making Ends Meet reported 24% in 2019, higher later)
  * median liquidity buffer ~1.5 months of expenses (MEM: ~half could cover <= 2 months after income loss)
  * spending mix: housing ~30%, food ~13%, utilities ~6% of income (BLS Consumer Expenditure Survey magnitudes)
  * transaction cadence/types modelled on real retail-bank statements (Berka/PKDD'99 categories)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Features derived in the curate stage from PRE-decision transactions (names shared with lineage + tests).
CASHFLOW_FEATURES = [
    "cf_income_mean_6m",
    "cf_income_cv_6m",
    "cf_income_min_month_6m",
    "cf_expense_to_income_6m",
    "cf_min_balance_6m",
    "cf_avg_balance_6m",
    "cf_overdraft_txn_count_6m",
    "cf_nsf_count_6m",
    "cf_housing_on_time_share_6m",
    "cf_gambling_share_6m",
    "cf_remittance_share_6m",
    "cf_debt_payments_to_income_6m",
    "cf_months_observed",
    "cf_verified_to_stated_income",
]
CASHFLOW_DESCRIPTIONS = {
    "cf_income_mean_6m": "Average monthly deposits (income) over 6 months before decision",
    "cf_income_cv_6m": "Income volatility: std/mean of monthly deposits",
    "cf_income_min_month_6m": "Lowest monthly income in the 6 months",
    "cf_expense_to_income_6m": "Total outflows / total inflows (6 months)",
    "cf_min_balance_6m": "Lowest running balance in the 6 months",
    "cf_avg_balance_6m": "Average running balance in the 6 months",
    "cf_overdraft_txn_count_6m": "Transactions that left the account overdrawn",
    "cf_nsf_count_6m": "Non-sufficient-funds fees charged",
    "cf_housing_on_time_share_6m": "Share of rent/mortgage payments made by the 5th of the month",
    "cf_gambling_share_6m": "Gambling spend / total outflows",
    "cf_remittance_share_6m": "Remittance / money-transfer spend / total outflows",
    "cf_debt_payments_to_income_6m": "Other debt payments / income",
    "cf_months_observed": "Months with any account activity",
    "cf_verified_to_stated_income": "Bank-verified annual income / stated annual income",
}

EMP_INCOME_CV = {"salaried": 0.05, "hourly": 0.15, "self_employed": 0.35, "retired": 0.04, "unemployed": 0.50}
REMIT_P = {"white": 0.05, "black": 0.12, "hispanic": 0.45, "asian": 0.35, "other": 0.20}
MERCHANTS = {
    "income": ["PAYROLL", "DIRECT DEP", "GIG PAYOUT", "BENEFIT"],
    "housing": ["RENT PMT", "MORTGAGE PMT"],
    "utilities": ["ELECTRIC CO", "WATER UTIL", "MOBILE CARRIER"],
    "debt_payment": ["CARD PAYMENT", "AUTO LOAN", "STUDENT LOAN"],
    "groceries": ["GROCERY", "SUPERMARKET"],
    "discretionary": ["RESTAURANT", "ONLINE SHOP", "FUEL", "PHARMACY", "TRAVEL"],
    "gambling": ["SPORTSBOOK", "CASINO"],
    "remittance": ["MONEY TRANSFER"],
    "savings": ["SAVINGS XFER"],
    "nsf_fee": ["NSF FEE"],
}


def latent_traits(
    rng: np.random.Generator,
    n: int,
    employment: np.ndarray,
    housing: np.ndarray,
    race: np.ndarray,
    bureau: np.ndarray,
    dti: np.ndarray,
    stated_income: np.ndarray,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    base_cv = np.array([EMP_INCOME_CV.get(e, 0.15) for e in employment])
    income_cv = np.clip(base_cv * rng.lognormal(0, 0.35, n), 0.01, 1.2)
    z_b = (bureau - 690) / 60
    buffer_months = np.clip(np.exp(np.log(cfg["median_buffer_months"]) + 0.45 * z_b + rng.normal(0, 0.8, n)), 0.02, 36)
    spend_pressure = np.clip(rng.normal(0.90, 0.10, n) + 0.25 * (dti - 0.3) - 0.03 * z_b, 0.55, 1.45)
    rent_late_p = np.clip(rng.beta(1.2, 14, n) + 0.25 * np.clip(spend_pressure - 1.0, 0, None), 0, 0.9)
    overstate = rng.random(n) < cfg["income_overstatement_share"]
    verified_income = stated_income / np.where(overstate, 1 + rng.uniform(0.2, 0.5, n), 1.0)
    gambler = rng.random(n) < 0.08
    gambling_share = np.where(gambler, rng.uniform(0.02, 0.12, n), 0.0)
    remitter = rng.random(n) < np.array([REMIT_P.get(r, 0.1) for r in race])
    remittance_share = np.where(remitter, rng.uniform(0.04, 0.15, n), 0.0)  # PLANTED PROXY (not causal)
    housing_share = np.where(np.isin(housing, ["rent", "mortgage"]), np.clip(rng.normal(0.30, 0.06, n), 0.12, 0.6), 0)
    return pd.DataFrame(
        {
            "income_cv": income_cv,
            "buffer_months": buffer_months,
            "spend_pressure": spend_pressure,
            "rent_late_p": rent_late_p,
            "overstated_income": overstate,
            "verified_monthly_income": verified_income / 12,
            "gambling_share": gambling_share,
            "remittance_share": remittance_share,
            "housing_share": housing_share,
            "employment_type": employment,
            "housing_status": housing,
            "dti": dti,
        }
    )


def cashflow_risk(lat: pd.DataFrame) -> np.ndarray:
    """PLANTED cash-flow signal added to the default hazard (log-odds). Remittances and gambling are NOT causal."""
    return (
        1.4 * (lat["income_cv"].to_numpy() - 0.15)
        - 0.30 * np.log(lat["buffer_months"].to_numpy() / 1.5)
        + 1.2 * (lat["spend_pressure"].to_numpy() - 0.90)
        + 2.0 * (lat["rent_late_p"].to_numpy() - 0.08)
        + 0.45 * lat["overstated_income"].to_numpy()
    )


def simulate_transactions(
    rng: np.random.Generator,
    application_ids: np.ndarray,
    decision_ts: pd.Series,
    lat: pd.DataFrame,
    months_before: int,
    post_months: np.ndarray,
) -> pd.DataFrame:
    """Monthly transaction rows for each applicant. post_months[i] extra months after the decision (0 for declines)."""
    n = len(application_ids)
    dec = pd.to_datetime(decision_ts).dt.floor("D").to_numpy().astype("datetime64[D]")
    inc = lat["verified_monthly_income"].to_numpy()
    cv = lat["income_cv"].to_numpy()
    emp = lat["employment_type"].to_numpy()
    total_months = months_before + post_months.astype(int)
    rows_app, rows_day, rows_amt, rows_cat, rows_desc = [], [], [], [], []

    def calendar_days(k: int, day_of_month: np.ndarray) -> np.ndarray:
        """Days-before-decision for a payment on a given CALENDAR day of the month nearest to window k."""
        anchor = dec - np.timedelta64((k - 1) * 30 + 15, "D")
        date = anchor.astype("datetime64[M]").astype("datetime64[D]") + (day_of_month - 1).astype("timedelta64[D]")
        days = (dec - date).astype(int)
        if k >= 1:  # must stay before the decision
            days = np.where(days < 1, days + 30, days)
        else:  # must stay after
            days = np.where(days >= 1, days - 30, days)
        return days

    def add(
        mask_app: np.ndarray,
        month_k: np.ndarray,
        day_in_month: np.ndarray,
        amount: np.ndarray,
        cat: str,
        days_override: np.ndarray | None = None,
    ):
        idx = np.where(mask_app)[0]
        if idx.size == 0:
            return
        # month_k: 1..months_before are before the decision (1 = most recent); 0, -1, ... are after
        days = (month_k[idx] - 1) * 30 + (30 - day_in_month[idx]) if days_override is None else days_override[idx]
        rows_app.append(idx)
        rows_day.append(days.astype(int))
        rows_amt.append(amount[idx])
        rows_cat.append(np.full(idx.size, cat, dtype=object))
        names = MERCHANTS[cat]
        rows_desc.append(np.array(names, dtype=object)[rng.integers(0, len(names), idx.size)])

    max_post = int(post_months.max()) if n else 0
    for k in range(months_before, -max_post, -1):  # chronological: oldest month first
        active = total_months >= (months_before - k + 1)
        mk = np.full(n, k)
        month_income = inc * np.clip(1 + cv * rng.normal(0, 1, n), 0, None)
        # income deposits: salaried/retired 1, hourly 2, self-employed/unemployed 3 irregular
        n_dep = np.select([np.isin(emp, ["salaried", "retired"]), emp == "hourly"], [1, 2], 3)
        for j in range(3):
            m = active & (n_dep > j)
            add(m, mk, np.where(n_dep == 1, 25, rng.integers(1, 29, n)), month_income / n_dep, "income")
        housing_amt = -inc * lat["housing_share"].to_numpy()
        late = rng.random(n) < lat["rent_late_p"].to_numpy()
        pay_day = np.where(late, rng.integers(8, 25, n), rng.integers(1, 4, n))  # calendar day of month
        add(active & (housing_amt < 0), mk, pay_day, housing_amt, "housing", calendar_days(k, pay_day))
        add(active, mk, rng.integers(5, 20, n), -inc * rng.uniform(0.04, 0.08, n), "utilities")
        debt_amt = -inc * np.clip(lat["dti"].to_numpy() - 0.1, 0, None) * 0.6
        add(active & (debt_amt < -1), mk, rng.integers(10, 16, n), debt_amt, "debt_payment")
        for _ in range(2):
            add(active, mk, rng.integers(1, 29, n), -inc * rng.uniform(0.05, 0.08, n), "groceries")
        gamb = -inc * lat["gambling_share"].to_numpy() * rng.uniform(0.5, 1.5, n)
        add(active & (gamb < 0), mk, rng.integers(1, 29, n), gamb, "gambling")
        remit = -inc * lat["remittance_share"].to_numpy() * rng.uniform(0.7, 1.3, n)
        add(active & (remit < 0), mk, rng.integers(1, 29, n), remit, "remittance")
        committed = -(housing_amt + debt_amt + gamb + remit) + inc * 0.19  # + utilities & groceries (approx)
        disc = np.clip(lat["spend_pressure"].to_numpy() * month_income - committed, 0, None)
        for _ in range(2):
            add(active, mk, rng.integers(1, 29, n), -disc / 2 * rng.uniform(0.8, 1.2, n), "discretionary")

    app = np.concatenate(rows_app)
    days = np.concatenate(rows_day)
    tx = pd.DataFrame(
        {
            "app_idx": app,
            "days_before_decision": days,
            "amount": np.concatenate(rows_amt),
            "category": np.concatenate(rows_cat),
            "description": np.concatenate(rows_desc),
        }
    )
    # chronological order within applicant (larger days_before = earlier), deposits before debits on the same day
    tx["is_debit"] = tx["amount"] < 0
    tx = tx.sort_values(
        ["app_idx", "days_before_decision", "is_debit"], ascending=[True, False, True], kind="mergesort"
    ).reset_index(drop=True)
    # opening balance = liquidity buffer expressed in months of spending
    start_balance = lat["buffer_months"].to_numpy() * lat["spend_pressure"].to_numpy() * inc
    tx["balance_after"] = tx.groupby("app_idx")["amount"].cumsum() + start_balance[tx["app_idx"].to_numpy()]
    # NSF fee when a debit takes the balance from >= 0 to < 0 (the payment "bounces"); single pass
    prev_balance = (
        tx.groupby("app_idx")["balance_after"]
        .shift(1)
        .fillna(pd.Series(start_balance[tx["app_idx"].to_numpy()], index=tx.index))
    )
    nsf = tx["is_debit"] & (tx["balance_after"] < 0) & (prev_balance >= 0)
    fees = tx.loc[nsf, ["app_idx", "days_before_decision"]].copy()
    fees["amount"] = -35.0
    fees["category"] = "nsf_fee"
    fees["description"] = "NSF FEE"
    fees["is_debit"] = True
    tx = pd.concat([tx, fees], ignore_index=True).sort_values(
        ["app_idx", "days_before_decision", "is_debit"], ascending=[True, False, True], kind="mergesort"
    )
    tx["balance_after"] = tx.groupby("app_idx")["amount"].cumsum() + start_balance[tx["app_idx"].to_numpy()]
    tx["application_id"] = np.asarray(application_ids)[tx["app_idx"].to_numpy()]
    tx["txn_date"] = dec[tx["app_idx"].to_numpy()] - tx["days_before_decision"].to_numpy().astype("timedelta64[D]")
    tx["txn_date"] = pd.to_datetime(tx["txn_date"]).dt.date
    out = tx[
        ["application_id", "txn_date", "days_before_decision", "amount", "balance_after", "category", "description"]
    ].reset_index(drop=True)
    out["amount"] = out["amount"].round(2)
    out["balance_after"] = out["balance_after"].round(2)
    out["days_before_decision"] = out["days_before_decision"].astype("int32")
    return out


# ---- curate-stage derivation (single implementation; SQL is portable across DuckDB and Databricks) --------------
def monthly_sql(fq_transactions: str, months: int) -> str:
    mb = "CAST(floor((days_before_decision - 1) / 30) AS INT) + 1"
    return (
        f"SELECT application_id, {mb} AS month_back, "
        "sum(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS income, "
        "sum(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS outflows, "
        "sum(CASE WHEN category = 'housing' THEN -amount ELSE 0 END) AS housing, "
        "sum(CASE WHEN category = 'housing' AND day(txn_date) <= 5 THEN 1 ELSE 0 END) AS housing_on_time_n, "
        "sum(CASE WHEN category = 'housing' THEN 1 ELSE 0 END) AS housing_n, "
        "sum(CASE WHEN category = 'gambling' THEN -amount ELSE 0 END) AS gambling, "
        "sum(CASE WHEN category = 'remittance' THEN -amount ELSE 0 END) AS remittance, "
        "sum(CASE WHEN category = 'debt_payment' THEN -amount ELSE 0 END) AS debt_payments, "
        "sum(CASE WHEN category = 'nsf_fee' THEN 1 ELSE 0 END) AS nsf_count, "
        "sum(CASE WHEN balance_after < 0 THEN 1 ELSE 0 END) AS overdraft_txns, "
        "min(balance_after) AS min_balance, avg(balance_after) AS avg_balance, count(*) AS n_txn "
        f"FROM {fq_transactions} "
        # THE anti-leakage guard: only transactions strictly before the decision, within the look-back window
        f"WHERE days_before_decision >= 1 AND days_before_decision <= {int(months) * 30} "
        f"GROUP BY application_id, {mb}"
    )


def summarize_monthly(monthly: pd.DataFrame, stated_income: pd.Series) -> pd.DataFrame:
    """Per-applicant cf_* features from the monthly table (stated_income indexed by application_id)."""
    g = monthly.groupby("application_id")
    inc_mean = g["income"].mean()
    s_out, s_in = g["outflows"].sum(), g["income"].sum()
    hn = g["housing_n"].sum()
    out = pd.DataFrame(
        {
            "cf_income_mean_6m": inc_mean,
            "cf_income_cv_6m": g["income"].std(ddof=0) / inc_mean.replace(0, np.nan),
            "cf_income_min_month_6m": g["income"].min(),
            "cf_expense_to_income_6m": s_out / s_in.replace(0, np.nan),
            "cf_min_balance_6m": g["min_balance"].min(),
            "cf_avg_balance_6m": g["avg_balance"].mean(),
            "cf_overdraft_txn_count_6m": g["overdraft_txns"].sum(),
            "cf_nsf_count_6m": g["nsf_count"].sum(),
            "cf_housing_on_time_share_6m": g["housing_on_time_n"].sum() / hn.replace(0, np.nan),
            "cf_gambling_share_6m": g["gambling"].sum() / s_out.replace(0, np.nan),
            "cf_remittance_share_6m": g["remittance"].sum() / s_out.replace(0, np.nan),
            "cf_debt_payments_to_income_6m": g["debt_payments"].sum() / s_in.replace(0, np.nan),
            "cf_months_observed": g["month_back"].nunique(),
        }
    )
    out["cf_verified_to_stated_income"] = (out["cf_income_mean_6m"] * 12) / stated_income.reindex(out.index)
    return out.round(4).reset_index()
