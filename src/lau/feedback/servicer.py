"""The simulated loan servicer: the status feed a servicing system would send for loans the decision API approved.

Each run covers the latest completed simulated month (the traffic clock, ops.sim_clock) once:
  * booking: that month's approvals, and the referrals a simulated underwriter approves, become loans when the
    applicant takes them up;
  * performance: each new loan's whole monthly path comes from the training data's own simulator
    (synth.generator._simulate_performance), driven by the applicant's latent risk, and is kept in
    simulation.performance (harness only);
  * feed: booking records for new loans, the month's status record for every open loan, and corrections. A small
    share of status records is first reported wrong (simulation.misreports) and corrected in the next feed; a very
    small share is malformed on purpose, for the ingestion's expectations to quarantine.
The feed is one JSON-lines file per month in the simulation.servicer_feed volume: loan_feed/<month>/feed-<month>.jsonl.
"""

from __future__ import annotations

import json
import math
import zlib
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.settings import get_settings
from lau.store import get_store

FEED_DIR = "loan_feed"
FLAGS = [
    "charge_off_flag",
    "bankruptcy_flag",
    "settlement_flag",
    "forbearance_flag",
    "payoff_flag",
    "fraud_flag",
    "deceased_flag",
]
STATUS_FIELDS = ["status", "dpd", "balance", "past_due_amount", "payment_amount", "scheduled_payment", *FLAGS]
TERMINAL = {"charged_off", "bankrupt", "settled", "fraud", "deceased", "paid_off"}
BREAKAGES = ("missing_loan_id", "negative_balance", "unknown_status", "bad_dpd", "unparseable")


def _cfg() -> dict:
    return get_settings().feedback["servicer"]


def _seed(tag: str) -> int:
    return int(get_settings().synth["seed"]) + zlib.crc32(tag.encode()) % 1_000_000


def feed_volume():
    from lau.governance.uc_layout import SERVICER_VOLUME
    from lau.volumes import volume

    return volume("simulation", SERVICER_VOLUME)


def feed_path(month: pd.Period) -> str:
    return f"{FEED_DIR}/{month}/feed-{month}.jsonl"


def latest_completed_month() -> pd.Period | None:
    """The newest simulated month whose applications have all been sent (None before the first origination)."""
    from lau.decision import traffic

    if not get_store("harness").table_exists("ops", "sim_clock"):
        return None
    return traffic.current_month() - 1


# ---- booking ------------------------------------------------------------------------------------------------------
def _candidates(month: pd.Period) -> pd.DataFrame:
    """Approved and referred decisions for synthetic applications decided for `month`, with inputs and latent risk."""
    st = get_store("harness")
    if not all(
        st.table_exists(k, t)
        for k, t in (("ops", "decisions"), ("curated", "decision_inputs"), ("simulation", "truth"))
    ):
        return pd.DataFrame()
    d = st.query(
        f"SELECT d.decision_id, d.application_id, d.decision, d.decided_at, i.application_json, t.latent_risk "
        f"FROM {st.fq('ops', 'decisions')} d "
        f"JOIN {st.fq('curated', 'decision_inputs')} i ON d.decision_id = i.decision_id "
        f"JOIN {st.fq('simulation', 'truth')} t ON d.application_id = t.application_id "
        f"WHERE NOT d.is_test AND d.decision IN ('approve', 'refer') AND substr(d.decision_date, 1, 7) = '{month}'"
    )
    if d.empty:
        return d
    return d.sort_values("decided_at").drop_duplicates("application_id", keep="last").reset_index(drop=True)


def book(month: pd.Period) -> pd.DataFrame:
    c = _candidates(month)
    cols = [
        "loan_id",
        "application_id",
        "decision_id",
        "approved_as",
        "booked_month",
        "loan_amount",
        "term_months",
        "interest_rate",
        "scheduled_payment",
        "latent_risk",
    ]
    if c.empty:
        return pd.DataFrame(columns=cols)
    cfg = _cfg()
    c = c.sort_values("application_id").reset_index(drop=True)  # draws do not depend on query order
    rng = np.random.default_rng(_seed(f"book-{month}"))
    u_refer, u_take = rng.random(len(c)), rng.random(len(c))
    approved = (c["decision"] == "approve") | ((c["decision"] == "refer") & (u_refer < cfg["referral_approval_rate"]))
    booked = c[approved & (u_take < cfg["take_up_rate"])].copy()
    app = pd.DataFrame([json.loads(x) for x in booked["application_json"]], index=booked.index)
    return pd.DataFrame(
        {
            "loan_id": "L" + booked["application_id"].str[1:],
            "application_id": booked["application_id"],
            "decision_id": booked["decision_id"],
            "approved_as": np.where(booked["decision"] == "approve", "approve", "referral_approved"),
            "booked_month": str(month),
            "loan_amount": pd.to_numeric(app["loan_amount"]),
            "term_months": pd.to_numeric(app["term_months"]).astype(int),
            "interest_rate": pd.to_numeric(app["interest_rate"]),
            "scheduled_payment": pd.to_numeric(app["scheduled_payment"]),
            "latent_risk": booked["latent_risk"].astype(float),
        }
    )[cols].reset_index(drop=True)


def simulate(loans: pd.DataFrame, month: pd.Period) -> pd.DataFrame:
    """The whole monthly path of each new loan, by the training data's own performance simulator."""
    from lau.synth.generator import _simulate_performance

    s = get_settings().synth
    max_mob = int(s["max_perf_months"])
    apps = loans[["application_id", "loan_amount", "interest_rate", "scheduled_payment"]].assign(
        origination_month=str(month)
    )
    perf, _ = _simulate_performance(
        np.random.default_rng(_seed(f"perf-{month}")),
        apps.reset_index(drop=True),
        loans["latent_risk"].to_numpy(dtype=float),
        month + max_mob,
        pd.Period(s["drift_start_month"], "M"),
        max_mob,
    )
    return perf.assign(booked_month=str(month))


# ---- the feed -----------------------------------------------------------------------------------------------------
def _plain(v):
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _status_records(rows: pd.DataFrame, record_type: str, month: pd.Period) -> list[dict]:
    out = []
    for r in rows.to_dict("records"):
        out.append(
            {
                "record_type": record_type,
                "reported_month": str(month),
                "loan_id": r["loan_id"],
                "period_month": r["period_month"],
                **{k: _plain(r[k]) for k in STATUS_FIELDS},
            }
        )
    return out


def _misreport(rows: pd.DataFrame) -> pd.DataFrame:
    """What a servicer gets wrong before correcting it: a payment not yet applied shows as 30 days more past due."""
    bad = rows.copy()
    bad["dpd"] = np.minimum(bad["dpd"] + 30, 180)
    bad["past_due_amount"] = (bad["past_due_amount"] + bad["scheduled_payment"]).round(2)
    bad["payment_amount"] = 0.0
    bad["status"] = "delinquent"
    return bad


def _break(record: dict, how: str) -> dict | str:
    r = dict(record)
    if how == "missing_loan_id":
        r["loan_id"] = None
    elif how == "negative_balance":
        r["balance"] = -abs(float(r.get("balance") or 0)) - 1.0
    elif how == "unknown_status":
        r["status"] = "in_review"
    elif how == "bad_dpd":
        r["dpd"] = 45
    else:  # unparseable: a truncated line
        return json.dumps(r)[:40]
    return r


def _first_month() -> pd.Period | None:
    st = get_store("harness")
    if not st.table_exists("ops", "sim_clock"):
        return None
    df = st.query(f"SELECT min(from_month) AS m FROM {st.fq('ops', 'sim_clock')}")
    return pd.Period(str(df["m"].iloc[0]), "M") if len(df) and df["m"].iloc[0] else None


def run(log=print) -> dict:
    """Write the feed for every completed simulated month that has none yet, oldest first (a missed day catches up)."""
    last, first = latest_completed_month(), _first_month()
    if last is None or first is None:
        return {"written": [], "reason": "no simulated month has completed yet (no synthetic traffic)"}
    vol = feed_volume()
    months = [m for m in pd.period_range(first, last, freq="M") if vol.read(feed_path(m)) is None]
    if not months:
        log(f"servicer: the feed is up to date (through {last})")
    return {"written": [write_month(m, log) for m in months]}


def write_month(month: pd.Period, log=print) -> dict:
    """The feed for one simulated month: bookings, status records, corrections, a few malformed records."""
    st = get_store("harness")
    vol = feed_volume()
    path = feed_path(month)
    cfg = _cfg()

    loans = book(month)
    if len(loans):
        st.write_df("simulation", "bookings", loans, mode="replace_partition", partition={"booked_month": str(month)})
        st.write_df(
            "simulation",
            "performance",
            simulate(loans, month),
            mode="replace_partition",
            partition={"booked_month": str(month)},
        )
    status = pd.DataFrame()
    if st.table_exists("simulation", "performance"):
        status = st.query(
            f"SELECT * FROM {st.fq('simulation', 'performance')} WHERE period_month = '{month}' ORDER BY loan_id"
        )
    rng = np.random.default_rng(_seed(f"feed-{month}"))
    wrong = (rng.random(len(status)) < cfg["misreport_rate"]) & ~status.get("status", pd.Series(dtype=str)).isin(
        TERMINAL
    )
    reported = status.copy()
    if wrong.any():
        reported.loc[wrong] = _misreport(status.loc[wrong])
        st.write_df(
            "simulation",
            "misreports",
            status.loc[wrong, ["loan_id", "period_month"]].assign(reported_month=str(month)),
            mode="append",
        )
    corrections = pd.DataFrame()
    if st.table_exists("simulation", "misreports"):
        corrections = st.query(
            f"SELECT p.* FROM {st.fq('simulation', 'performance')} p JOIN {st.fq('simulation', 'misreports')} m "
            f"ON p.loan_id = m.loan_id AND p.period_month = m.period_month WHERE m.reported_month = '{month - 1}'"
        )

    records: list[dict | str] = [
        {
            "record_type": "booking",
            "reported_month": str(month),
            **{k: _plain(v) for k, v in r.items() if k != "latent_risk"},
        }
        for r in loans.to_dict("records")
    ]
    status_records = _status_records(reported, "status", month)
    broken = rng.random(len(status_records)) < cfg["malformed_rate"]
    kinds = rng.choice(BREAKAGES, size=len(status_records))
    records += [_break(r, k) if b else r for r, b, k in zip(status_records, broken, kinds, strict=True)]
    records += _status_records(corrections, "correction", month)
    lines = [x if isinstance(x, str) else json.dumps({**x, "record_seq": i}) for i, x in enumerate(records)]
    vol.write(path, ("\n".join(lines) + "\n").encode())
    summary = {
        "reported_month": str(month),
        "file": path,
        "bookings": len(loans),
        "status_records": len(status_records),
        "misreported": int(wrong.sum()),
        "corrections": len(corrections),
        "malformed": int(broken.sum()),
        "written_at": datetime.now(UTC).replace(tzinfo=None),
    }
    st.write_df("simulation", "feed_runs", pd.DataFrame([summary]), mode="append")
    log(
        f"servicer feed {month}: {summary['bookings']} new loans, {summary['status_records']} status records "
        f"({summary['misreported']} misreported), {summary['corrections']} corrections, "
        f"{summary['malformed']} malformed"
    )
    return summary
