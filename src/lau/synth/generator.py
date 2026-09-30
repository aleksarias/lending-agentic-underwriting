"""Reproducible synthetic lending data: applications + RAW monthly loan performance (never a finished label).

Planted structure (recorded in `ground_truth`):
  * true signal: 5 causal features drive a latent monthly delinquency hazard
  * leakage: `acct_review_flag` is populated after the decision (from early servicing events); its timestamp
    column `acct_review_ts` is always after `decision_ts`. Lineage metadata deliberately says "unknown".
  * time drift: from `drift_start_month` the channel mix, income level, a coefficient and a macro shock shift
  * protected-class proxy: `geo_affluence_idx` is a ZIP-level index that tracks race/ethnicity composition and is
    NOT causal for default
  * materiality: a small share of "short payers" roll into DPD buckets with trivial past-due balances
  * selection: a legacy score approves ~70%; declines have no performance (reject-inference limitation)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

CAUSAL = {
    "bureau_score": -0.012,  # per point vs 690
    "dti": 2.2,  # vs 0.30
    "util_revolving": 1.4,  # vs 0.40 (halves after drift)
    "inq_6m": 0.18,  # vs 1.2
    "pmt_to_income": 6.0,  # vs 0.08
}
# Monthly current->30 DPD roll is sigmoid(risk); roll-forward once delinquent uses risk relative to this intercept.
RISK_INTERCEPT = -4.6
RACES = np.array(["white", "black", "hispanic", "asian", "other"])
RACE_P = np.array([0.60, 0.13, 0.17, 0.06, 0.04])
STATES = np.array([f"S{i:02d}" for i in range(50)])
CHANNELS = np.array(["branch", "web", "partner_api", "broker"])
PRODUCTS = np.array(["personal", "debt_consolidation", "auto_refi", "home_improvement"])
EMPLOYMENT = np.array(["salaried", "hourly", "self_employed", "retired", "unemployed"])
HOUSING = np.array(["own", "mortgage", "rent", "other"])
PURPOSE = np.array(["consolidation", "medical", "car", "home", "vacation", "business", "other"])
DEVICE_OS = np.array(["ios", "android", "windows", "macos", "linux", "unknown"])

PII_COLUMNS = ["first_name", "surname", "email", "phone", "ssn", "street_address", "date_of_birth", "ip_address"]
PROTECTED_COLUMNS = ["race_ethnicity", "sex", "age", "age_62_plus"]


@dataclass
class SynthData:
    applications: pd.DataFrame
    performance: pd.DataFrame
    protected: pd.DataFrame
    field_lineage: pd.DataFrame
    new_applications: pd.DataFrame
    ground_truth: dict[str, Any] = field(default_factory=dict)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _applications(
    rng: np.random.Generator, n: int, months: list[pd.Period], drift_start: pd.Period, n_noise: int, id_prefix: str
) -> tuple[pd.DataFrame, np.ndarray, pd.DataFrame]:
    # Origination month with mild growth
    w = np.linspace(1.0, 1.6, len(months))
    m_idx = rng.choice(len(months), size=n, p=w / w.sum())
    period = np.array([months[i] for i in m_idx], dtype=object)
    post_drift = np.array([p >= drift_start for p in period])

    day = rng.integers(0, 28, size=n)
    app_ts = (
        pd.to_datetime([p.to_timestamp() for p in period])
        + pd.to_timedelta(day, unit="D")
        + pd.to_timedelta(rng.integers(0, 86400, size=n), unit="s")
    )
    decision_ts = app_ts + pd.to_timedelta(rng.integers(60, 3 * 86400, size=n), unit="s")

    # Protected attributes (synthetic) + ZIP composition proxy
    race = rng.choice(RACES, size=n, p=RACE_P)
    sex = rng.choice(np.array(["male", "female"]), size=n)
    age = np.clip(rng.normal(44, 14, size=n), 21, 85).round().astype(int)
    n_zip = 900
    zip_minority_share = rng.beta(1.2, 3.0, size=n_zip)  # composition per zip3
    minority = race != "white"
    # sample zip weighted by composition consistent with the applicant's group
    zw_min = zip_minority_share / zip_minority_share.sum()
    zw_maj = (1 - zip_minority_share) / (1 - zip_minority_share).sum()
    zip_idx = np.where(minority, rng.choice(n_zip, size=n, p=zw_min), rng.choice(n_zip, size=n, p=zw_maj))
    zip3 = np.array([f"{100 + z:03d}" for z in zip_idx])
    geo_affluence_idx = (1.0 - zip_minority_share[zip_idx]) * 100 + rng.normal(0, 6, size=n)  # PLANTED PROXY

    # Causal features
    thin_file = rng.random(n) < 0.12
    bureau = np.clip(rng.normal(690, 60, size=n) - 10 * post_drift, 450, 850)
    dti = np.clip(rng.beta(2.2, 5.0, size=n) * 0.9, 0.0, 0.75)
    util = rng.beta(2.0, 3.0, size=n)
    inq = rng.poisson(1.2 + 0.4 * post_drift, size=n)
    income = np.exp(rng.normal(11.0, 0.45, size=n)) * (1 + 0.08 * post_drift)
    loan_amount = np.clip(np.round(np.exp(rng.normal(9.3, 0.6, size=n)), -2), 1000, 60000)
    term = rng.choice(np.array([36, 60]), size=n, p=[0.65, 0.35])

    channel_p_pre = np.array([0.30, 0.45, 0.10, 0.15])
    channel_p_post = np.array([0.20, 0.40, 0.30, 0.10])
    channel = np.where(
        post_drift, rng.choice(CHANNELS, size=n, p=channel_p_post), rng.choice(CHANNELS, size=n, p=channel_p_pre)
    )

    # Legacy score used by the current policy (decision-time only)
    legacy_logit = (
        -0.010 * (bureau - 690)
        + 1.6 * (dti - 0.3)
        + 0.7 * (util - 0.4)
        + 0.12 * (inq - 1.2)
        + 0.3 * thin_file
        + rng.normal(0, 0.45, size=n)
    )
    rate = np.clip(0.07 + 0.06 * _sigmoid(legacy_logit) + rng.normal(0, 0.01, size=n), 0.05, 0.30)
    r = rate / 12
    sched_pmt = loan_amount * r / (1 - (1 + r) ** (-term))
    pti = sched_pmt / (income / 12)

    util_coef = np.where(post_drift, CAUSAL["util_revolving"] / 2, CAUSAL["util_revolving"])
    risk = (
        RISK_INTERCEPT
        + CAUSAL["bureau_score"] * (bureau - 690)
        + CAUSAL["dti"] * (dti - 0.30)
        + util_coef * (util - 0.40)
        + CAUSAL["inq_6m"] * (inq - 1.2)
        + CAUSAL["pmt_to_income"] * (pti - 0.08)
        + 0.35 * thin_file
        + 0.35 * (channel == "partner_api")
        + rng.normal(0, 0.35, size=n)
    )

    df = pd.DataFrame(
        {
            "application_id": [f"{id_prefix}{i:07d}" for i in range(n)],
            "application_ts": app_ts,
            "decision_ts": decision_ts,
            "origination_month": [str(p) for p in period],
            "channel": channel,
            "product": rng.choice(PRODUCTS, size=n, p=[0.4, 0.35, 0.15, 0.10]),
            "state": rng.choice(STATES, size=n),
            "zip3": zip3,
            "geo_affluence_idx": geo_affluence_idx.round(2),
            "employer_id": np.array([f"E{int(x):05d}" for x in np.minimum(rng.zipf(1.3, size=n), 99999)]),
            "employment_type": rng.choice(EMPLOYMENT, size=n, p=[0.55, 0.25, 0.12, 0.06, 0.02]),
            "employment_years": np.clip(rng.exponential(6, size=n), 0, 45).round(1),
            "housing_status": rng.choice(HOUSING, size=n, p=[0.15, 0.35, 0.45, 0.05]),
            "purpose": rng.choice(PURPOSE, size=n),
            "annual_income": income.round(0),
            "loan_amount": loan_amount,
            "term_months": term,
            "interest_rate": rate.round(4),
            "scheduled_payment": sched_pmt.round(2),
            "pmt_to_income": pti.round(4),
            "thin_file": thin_file,
            "bureau_score": np.where(thin_file & (rng.random(n) < 0.7), np.nan, bureau.round(0)),
            "dti": dti.round(4),
            "util_revolving": np.where(thin_file & (rng.random(n) < 0.5), np.nan, util.round(4)),
            "inq_6m": inq,
            "num_open_trades": np.where(thin_file, rng.poisson(1, size=n), rng.poisson(7, size=n)),
            "num_delinq_24m": rng.poisson(np.clip(0.3 + 0.8 * _sigmoid(risk + 2), 0, None)),
            "months_since_last_delinq": np.where(rng.random(n) < 0.6, np.nan, rng.integers(1, 120, size=n)),
            "total_rev_balance": (util * rng.lognormal(9.5, 0.7, size=n)).round(0),
            "email_domain_age_days": rng.integers(1, 9000, size=n),
            "device_os": rng.choice(DEVICE_OS, size=n, p=[0.35, 0.30, 0.18, 0.12, 0.02, 0.03]),
            "session_duration_s": np.clip(rng.lognormal(5.5, 0.8, size=n), 20, 20000).round(0),
            "ip_distance_km": np.clip(rng.exponential(40, size=n) + 400 * (rng.random(n) < 0.03), 0, 5000).round(1),
            "legacy_score": (1000 * (1 - _sigmoid(legacy_logit))).round(0),
        }
    )

    # Noise / redundant bureau attributes: ~30% are noisy proxies of causal inputs (discoverable but redundant)
    latent = np.column_stack([(bureau - 690) / 60, (dti - 0.3) / 0.12, (util - 0.4) / 0.2, (inq - 1.2) / 1.1])
    noise_cols: dict[str, np.ndarray] = {}
    correlated: list[str] = []
    for j in range(n_noise):
        name = f"bur_attr_{j + 1:03d}"
        if j % 10 < 3:
            wts = rng.normal(0, 1, size=latent.shape[1])
            val = latent @ wts * 0.5 + rng.normal(0, 1, size=n)
            correlated.append(name)
        else:
            val = rng.normal(0, 1, size=n) if j % 2 else rng.gamma(2, 2, size=n)
        miss = rng.random(n) < rng.uniform(0, 0.2)
        val = np.where(miss | thin_file, np.nan, val)  # MCAR + thin-file MNAR
        noise_cols[name] = np.round(val, 4)
    df = pd.concat([df, pd.DataFrame(noise_cols)], axis=1)

    # Synthetic PII (fake formats; SSNs start with 9 => never valid)
    first = np.array(["alex", "sam", "jordan", "taylor", "casey", "riley", "morgan", "jamie", "drew", "quinn"])
    last = np.array(["smith", "garcia", "lee", "patel", "nguyen", "brown", "khan", "silva", "cohen", "okafor"])
    fn, ln = rng.choice(first, size=n), rng.choice(last, size=n)
    df["first_name"] = fn
    df["surname"] = ln
    df["email"] = [f"{a}.{b}{i}@example.com" for i, (a, b) in enumerate(zip(fn, ln, strict=True))]
    df["phone"] = [f"555-{rng.integers(100, 999)}-{rng.integers(1000, 9999)}" for _ in range(n)]
    df["ssn"] = [f"9{rng.integers(10, 99)}-{rng.integers(10, 99)}-{rng.integers(1000, 9999)}" for _ in range(n)]
    df["street_address"] = [f"{rng.integers(1, 9999)} Synthetic St" for _ in range(n)]
    df["date_of_birth"] = (pd.Timestamp("2026-01-01") - pd.to_timedelta(age * 365, unit="D")).date
    df["ip_address"] = [f"10.{rng.integers(0, 255)}.{rng.integers(0, 255)}.{rng.integers(1, 254)}" for _ in range(n)]

    protected = pd.DataFrame(
        {
            "application_id": df["application_id"],
            "race_ethnicity": race,
            "sex": sex,
            "age": age,
            "age_62_plus": np.where(age >= 62, "true", "false"),
        }
    )
    return df, risk, protected


def _simulate_performance(
    rng: np.random.Generator,
    apps: pd.DataFrame,
    risk: np.ndarray,
    as_of: pd.Period,
    drift_start: pd.Period,
    max_mob: int,
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    n = len(apps)
    orig = [pd.Period(m, "M") for m in apps["origination_month"]]
    avail = np.array([(as_of - p).n for p in orig])  # months observable after origination
    horizon = np.minimum(avail, max_mob)
    orig_ord = np.array([p.ordinal for p in orig])
    drift_ord = drift_start.ordinal

    pmt = apps["scheduled_payment"].to_numpy()
    rate_m = apps["interest_rate"].to_numpy() / 12
    balance = apps["loan_amount"].to_numpy().astype(float)
    risk_pct = pd.Series(risk).rank(pct=True).to_numpy()

    fraud = rng.random(n) < 0.004
    short_payer = (rng.random(n) < 0.04) & (risk_pct < 0.6)
    bucket = np.zeros(n, dtype=int)  # 0=current, 1=30, ..., 6=180
    past_due = np.zeros(n)
    forb_left = np.zeros(n, dtype=int)
    active = horizon > 0
    rows: list[pd.DataFrame] = []
    first_30_mob = np.full(n, 0)

    for mob in range(1, max_mob + 1):
        idx = np.where(active & (horizon >= mob))[0]
        if idx.size == 0:
            break
        cal = orig_ord[idx] + mob
        macro = 0.25 * (cal >= drift_ord + 6)  # macro shock ~6 months after drift start
        season = 0.35 * np.exp(-(((mob - 9) / 6.0) ** 2))
        z = risk[idx] + macro + season
        b = bucket[idx]
        u = rng.random(idx.size)

        status = np.array(["current"] * idx.size, dtype=object)
        flags = {
            k: np.zeros(idx.size, dtype=int)
            for k in (
                "charge_off_flag",
                "bankruptcy_flag",
                "settlement_flag",
                "forbearance_flag",
                "payoff_flag",
                "fraud_flag",
                "deceased_flag",
            )
        }
        terminal = np.zeros(idx.size, dtype=bool)
        payment = pmt[idx].copy()

        in_forb = forb_left[idx] > 0
        # --- delinquency transitions (not in forbearance)
        rel = z - RISK_INTERCEPT
        p_roll_cur = _sigmoid(z)
        p_roll_del = _sigmoid(-0.5 + 0.8 * rel + 0.25 * b)
        p_cure = (1 - p_roll_del) * 0.55
        new_b = b.copy()
        cur = (b == 0) & ~in_forb
        dlq = (b > 0) & ~in_forb
        roll_c = cur & (u < p_roll_cur)
        new_b[roll_c] = 1
        roll_d = dlq & (u < p_roll_del)
        cure_d = dlq & ~roll_d & (u < p_roll_del + p_cure)
        new_b[roll_d] = b[roll_d] + 1
        new_b[cure_d] = 0

        # fraud: first-payment default pattern, confirmed around mob 3-4
        fr = fraud[idx]
        new_b[fr & (mob <= 4)] = np.minimum(mob, 3)

        # short payers: technical delinquency with trivial past-due balance
        sp = short_payer[idx] & ~in_forb & ~fr
        sp_short = sp & (rng.random(idx.size) < 0.25)
        sp_full = sp & ~sp_short & (rng.random(idx.size) < 0.35)
        new_b[sp_short] = np.minimum(b[sp_short] + 1, 3)
        new_b[sp_full] = 0

        # past-due amount
        pd_amt = past_due[idx].copy()
        pd_amt[new_b == 0] = 0.0
        normal_dlq = (new_b > 0) & ~sp_short
        pd_amt[normal_dlq] = new_b[normal_dlq] * pmt[idx][normal_dlq]
        pd_amt[sp_short] = pd_amt[sp_short] + rng.uniform(5, 15, size=sp_short.sum())
        payment[new_b > b] = 0.0
        payment[sp_short] = pmt[idx][sp_short] - rng.uniform(5, 15, size=sp_short.sum())

        # --- forbearance
        start_forb = (~in_forb) & (new_b <= 1) & (rng.random(idx.size) < 0.004 * (1 + 2 * _sigmoid(rel)))
        forb_left[idx[start_forb]] = 3
        now_forb = forb_left[idx] > 0
        flags["forbearance_flag"][now_forb] = 1
        status[now_forb] = "forbearance"
        payment[now_forb] = 0.0
        new_b[now_forb] = b[now_forb]  # DPD frozen
        forb_left[idx[now_forb]] -= 1

        # --- terminal events (at most one per loan-month; precedence below)
        dead = rng.random(idx.size) < 0.0004
        bk = (rng.random(idx.size) < 0.0015 * np.exp(0.6 * rel)) & ~dead
        settle = (new_b >= 3) & (rng.random(idx.size) < 0.08) & ~dead & ~bk
        co = ((new_b >= 6) | ((new_b >= 4) & (rng.random(idx.size) < 0.10))) & ~dead & ~bk & ~settle
        fraud_conf = fr & (mob == 4) & ~dead
        payoff = (new_b == 0) & ~now_forb & (rng.random(idx.size) < 0.012 * (1.6 - risk_pct[idx])) & ~dead & ~bk & ~fr
        for mask, flag, st in (
            (dead, "deceased_flag", "deceased"),
            (bk, "bankruptcy_flag", "bankrupt"),
            (fraud_conf & ~bk, "fraud_flag", "fraud"),
            (settle & ~fraud_conf, "settlement_flag", "settled"),
            (co & ~fraud_conf, "charge_off_flag", "charged_off"),
            (payoff & ~fraud_conf, "payoff_flag", "paid_off"),
        ):
            m = mask & ~terminal
            flags[flag][m] = 1
            status[m] = st
            terminal |= m

        dlq_now = (new_b > 0) & ~terminal & ~now_forb
        status[dlq_now] = "delinquent"

        # balance amortization (only when paid)
        bal = balance[idx]
        interest = bal * rate_m[idx]
        principal = np.clip(payment - interest, 0, None)
        bal = np.clip(bal - principal, 0, None)
        bal[flags["payoff_flag"] == 1] = 0.0
        payment[flags["payoff_flag"] == 1] = balance[idx][flags["payoff_flag"] == 1]
        balance[idx] = bal
        bucket[idx] = new_b
        past_due[idx] = pd_amt
        first_30_mob[idx[(new_b >= 1) & (first_30_mob[idx] == 0)]] = mob

        rows.append(
            pd.DataFrame(
                {
                    "application_id": apps["application_id"].to_numpy()[idx],
                    "mob": mob,
                    "_cal": cal,
                    "status": status,
                    "dpd": new_b * 30,
                    "balance": bal.round(2),
                    "past_due_amount": pd_amt.round(2),
                    "scheduled_payment": pmt[idx].round(2),
                    "payment_amount": np.clip(payment, 0, None).round(2),
                    **flags,
                }
            )
        )
        active[idx[terminal]] = False

    perf = pd.concat(rows, ignore_index=True)
    perf["period_month"] = pd.PeriodIndex.from_ordinals(perf.pop("_cal").to_numpy(), freq="M").astype(str)
    perf.insert(0, "loan_id", "L" + perf["application_id"].str[1:])
    return perf, {"first_30_mob": first_30_mob, "fraud": fraud, "short_payer": short_payer}


def generate(cfg: dict[str, Any], n_applications: int | None = None, seed: int | None = None) -> SynthData:
    seed = int(cfg["seed"] if seed is None else seed)
    n = int(n_applications or cfg["n_applications"])
    rng = np.random.default_rng(seed)
    start = pd.Period(cfg["start_month"], "M")
    months = [start + i for i in range(int(cfg["n_origination_months"]))]
    as_of = pd.Period(cfg["as_of_month"], "M")
    drift_start = pd.Period(cfg["drift_start_month"], "M")

    apps, risk, protected = _applications(rng, n, months, drift_start, int(cfg["n_noise_numeric"]), "A")

    # Legacy policy: approve best `approval_rate` by legacy score within each month
    rank = apps.groupby("origination_month")["legacy_score"].rank(pct=True, ascending=False)
    approved = (rank <= float(cfg["approval_rate"])).to_numpy()
    apps["approved"] = approved
    apps["loan_id"] = np.where(approved, "L" + apps["application_id"].str[1:], None)

    perf, aux = _simulate_performance(
        rng, apps.loc[approved].reset_index(drop=True), risk[approved], as_of, drift_start, int(cfg["max_perf_months"])
    )

    # PLANTED LEAKAGE: account-review flag set by servicing after early delinquency; timestamp post-decision.
    app_ok = apps.loc[approved].reset_index(drop=True)
    f30 = aux["first_30_mob"]
    review = (f30 > 0) & (f30 <= 6)
    review_ts = app_ok["decision_ts"] + pd.to_timedelta(np.where(review, f30 * 30, 180), unit="D")
    apps["acct_review_flag"] = np.nan
    apps["acct_review_ts"] = pd.NaT
    apps.loc[approved, "acct_review_flag"] = review.astype(float)
    apps.loc[approved, "acct_review_ts"] = review_ts.to_numpy()

    lineage = _lineage(apps.columns)

    # Post-as-of applications for shadow scoring (no performance)
    new_months = [as_of + 1 + i for i in range(3)]
    new_apps, _, _ = _applications(
        np.random.default_rng(seed + 1),
        int(cfg["n_new_applications"]),
        new_months,
        drift_start,
        int(cfg["n_noise_numeric"]),
        "N",
    )
    new_apps = new_apps.drop(columns=PII_COLUMNS)

    gt = {
        "seed": seed,
        "n_applications": n,
        "causal_features": list(CAUSAL),
        "causal_coefficients": CAUSAL,
        "correlated_redundant_features": [
            f"bur_attr_{j + 1:03d}" for j in range(int(cfg["n_noise_numeric"])) if j % 10 < 3
        ],
        "leakage_columns": ["acct_review_flag"],
        "leakage_timestamp_columns": {"acct_review_flag": "acct_review_ts"},
        "proxy_features": {"geo_affluence_idx": "race_ethnicity"},
        "protected_columns": PROTECTED_COLUMNS,
        "pii_columns": PII_COLUMNS,
        "drift": {
            "start_month": cfg["drift_start_month"],
            "changes": [
                "channel mix -> partner_api",
                "income +8%",
                "bureau_score -10",
                "util_revolving coefficient halves",
                "macro shock +0.25 logit from start+6m",
            ],
        },
        "materiality": {
            "short_payer_share": float(aux["short_payer"].mean()),
            "note": "short payers reach 30-90 DPD with <$50 past due",
        },
        "fraud_share": float(aux["fraud"].mean()),
        "approval_rate": float(approved.mean()),
        "as_of_month": cfg["as_of_month"],
    }
    return SynthData(apps, perf, protected, lineage, new_apps, gt)


def _lineage(columns: pd.Index) -> pd.DataFrame:
    src = {
        "bureau": [
            "bureau_score",
            "util_revolving",
            "inq_6m",
            "num_open_trades",
            "num_delinq_24m",
            "months_since_last_delinq",
            "total_rev_balance",
            "thin_file",
        ],
        "device": ["device_os", "session_duration_s", "ip_distance_km", "email_domain_age_days", "ip_address"],
        "application": [
            "channel",
            "product",
            "state",
            "zip3",
            "employer_id",
            "employment_type",
            "employment_years",
            "housing_status",
            "purpose",
            "annual_income",
            "loan_amount",
            "term_months",
            "dti",
        ],
        "pricing": ["interest_rate", "scheduled_payment", "pmt_to_income", "legacy_score"],
        "geo_vendor": ["geo_affluence_idx"],
        "crm": ["acct_review_flag", "acct_review_ts"],  # deliberately vague lineage (the leak)
    }
    rows = []
    for c in columns:
        source = next((k for k, v in src.items() if c in v), "bureau" if c.startswith("bur_attr_") else "application")
        available = "unknown" if source == "crm" else "decision"
        rows.append(
            {
                "column_name": c,
                "source_system": source,
                "available_at": available,
                "description": _DESCRIPTIONS.get(c, f"{source} attribute {c}"),
            }
        )
    return pd.DataFrame(rows)


_DESCRIPTIONS = {
    "bureau_score": "Credit bureau risk score at application",
    "dti": "Debt-to-income ratio (stated income, bureau debts)",
    "util_revolving": "Revolving credit utilization",
    "inq_6m": "Credit inquiries in last 6 months",
    "pmt_to_income": "Scheduled monthly payment / monthly income",
    "geo_affluence_idx": "Vendor ZIP-level affluence index",
    "acct_review_flag": "Account review indicator from CRM",
    "legacy_score": "Current production policy score",
    "employer_id": "Normalized employer identifier (high cardinality)",
}
