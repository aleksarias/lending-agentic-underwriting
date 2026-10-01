"""Loan status feed ingestion: expectations, quarantine, an append-only bitemporal history and restatements.

Every new file in the servicer volume (loan_feed/<month>/*.jsonl) is read once (ops.feed_files):
  * each record meets the expectations below or goes to ops.feed_quarantine with its reasons;
  * a file whose quarantined share exceeds feed.max_quarantine_share is held back whole (status "held"): nothing
    from it reaches the history until a person reviews it and releases it (`lau feed release <file>`), which
    ingests its valid records;
  * accepted bookings append to curated.loan_bookings; accepted status records and corrections append to
    curated.loan_performance_history, never updated in place. Valid time is the period_month the record describes;
    transaction time is the reported_month (simulated) and ingested_at (real) of the file that carried it;
  * a correction that changes what was known for a loan-month is a restatement (ops.feed_restatements);
  * curated.loan_performance_current holds the latest report per loan-month (rebuilt after each ingestion), and
    `as_known_at(month)` gives the history as it was known at the end of any reported month.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.feedback.servicer import FEED_DIR, FLAGS, STATUS_FIELDS, feed_volume
from lau.settings import get_settings
from lau.store import get_store

STATUSES = {
    "current",
    "delinquent",
    "forbearance",
    "charged_off",
    "bankrupt",
    "settled",
    "fraud",
    "deceased",
    "paid_off",
}
DPD_VALUES = {0, 30, 60, 90, 120, 150, 180}
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
KEY = ["loan_id", "period_month"]
HISTORY_COLUMNS = [
    "loan_id",
    "period_month",
    "record_type",
    "reported_month",
    "record_seq",
    "feed_file",
    "ingested_at",
    *STATUS_FIELDS,
]
BOOKING_COLUMNS = [
    "loan_id",
    "application_id",
    "decision_id",
    "approved_as",
    "booked_month",
    "loan_amount",
    "term_months",
    "interest_rate",
    "scheduled_payment",
    "reported_month",
    "feed_file",
    "ingested_at",
]


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


def _known_loans() -> set[str]:
    st = get_store("harness")
    if not st.table_exists("curated", "loan_bookings"):
        return set()
    return set(st.query(f"SELECT loan_id FROM {st.fq('curated', 'loan_bookings')}")["loan_id"].astype(str))


def check(record: dict, file_month: str, known: set[str]) -> list[str]:
    """Expectations for one record; an empty list means it is accepted."""
    kind = record.get("record_type")
    why: list[str] = []
    if kind not in ("booking", "status", "correction"):
        return [f"unknown record_type {kind!r}"]
    if not record.get("loan_id"):
        why.append("loan_id missing")
    if kind == "booking":
        if not record.get("application_id"):
            why.append("application_id missing")
        if (_num(record.get("loan_amount")) or 0) <= 0:
            why.append("loan_amount must be positive")
        if (_num(record.get("term_months")) or 0) <= 0:
            why.append("term_months must be positive")
        if record.get("booked_month") != file_month:
            why.append("booked_month differs from the file's month")
        return why
    period = str(record.get("period_month") or "")
    if not MONTH.match(period):
        why.append("period_month is not YYYY-MM")
    elif period > file_month:
        why.append("period_month is after the file's month")
    elif kind == "correction" and period >= file_month:
        why.append("a correction must describe an earlier month")
    if record.get("loan_id") and record["loan_id"] not in known:
        why.append("loan_id was never booked")
    if record.get("status") not in STATUSES:
        why.append(f"status {record.get('status')!r} is not a known status")
    dpd = _num(record.get("dpd"))
    if dpd is None or int(dpd) not in DPD_VALUES or dpd != int(dpd):
        why.append(f"dpd {record.get('dpd')!r} is not a 30-day bucket")
    for f in ("balance", "past_due_amount", "payment_amount"):
        v = _num(record.get(f))
        if v is None or v < 0:
            why.append(f"{f} must be zero or more")
    for f in FLAGS:
        if record.get(f) not in (0, 1):
            why.append(f"{f} must be 0 or 1")
    return why


def pending_files() -> list[str]:
    """Feed files never read (a held file waits for a person's release, not for the next run)."""
    st = get_store("harness")
    files = [f for f in feed_volume().list(FEED_DIR) if f.endswith(".jsonl")]
    if not st.table_exists("ops", "feed_files"):
        return files
    seen = st.query(f"SELECT feed_file FROM {st.fq('ops', 'feed_files')}")
    return [f for f in files if f not in set(seen["feed_file"].astype(str))]


def held_files() -> list[str]:
    st = get_store("harness")
    if not st.table_exists("ops", "feed_files"):
        return []
    df = st.query(f"SELECT feed_file, status, ingested_at FROM {st.fq('ops', 'feed_files')} ORDER BY ingested_at")
    last = df.drop_duplicates("feed_file", keep="last")
    return last.loc[last["status"] == "held", "feed_file"].astype(str).tolist()


def release(rel: str, by: str, log=print) -> dict:
    """A person reviewed a held file's quarantine: ingest its valid records (the bad ones stay quarantined)."""
    if rel not in held_files():
        raise ValueError(f"{rel} is not held")
    return ingest_file(rel, log, released_by=by)


def _current_known(keys: pd.DataFrame) -> pd.DataFrame:
    st = get_store("harness")
    if keys.empty or not st.table_exists("curated", "loan_performance_current"):
        return pd.DataFrame(columns=[*KEY, *STATUS_FIELDS])
    loans = ", ".join(f"'{x}'" for x in keys["loan_id"].astype(str).unique())
    cur = st.query(f"SELECT * FROM {st.fq('curated', 'loan_performance_current')} WHERE loan_id IN ({loans})")
    return cur.merge(keys[KEY].drop_duplicates(), on=KEY)


def ingest_file(rel: str, log=print, released_by: str | None = None) -> dict:
    st = get_store("harness")
    now = datetime.now(UTC).replace(tzinfo=None)
    file_month = rel.split("/")[1] if rel.count("/") >= 2 else ""
    raw = (feed_volume().read(rel) or b"").decode().splitlines()
    known = _known_loans()
    accepted: list[dict] = []
    quarantined: list[dict] = []
    for line in raw:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            quarantined.append({"raw": line[:2000], "reasons": "unparseable JSON"})
            continue
        if rec.get("record_type") == "booking" and rec.get("loan_id"):
            known.add(str(rec["loan_id"]))  # status records in the same file may follow their booking
        why = check(rec, file_month, known)
        if why:
            quarantined.append({"raw": line[:2000], "reasons": "; ".join(why), "loan_id": rec.get("loan_id")})
        else:
            accepted.append(rec)
    total = len(accepted) + len(quarantined)
    share = len(quarantined) / total if total else 0.0
    limit = float(get_settings().feedback["feed"]["max_quarantine_share"])
    status = "ingested" if released_by or share <= limit else "held"
    restated = 0
    if quarantined and not released_by:  # a release re-reads the file: its quarantine was recorded the first time
        q = pd.DataFrame(quarantined).assign(feed_file=rel, file_month=file_month, ingested_at=now, file_status=status)
        st.write_df(
            "ops",
            "feed_quarantine",
            q.reindex(columns=["feed_file", "file_month", "loan_id", "reasons", "raw", "ingested_at", "file_status"]),
            mode="append",
        )
    if status == "ingested" and accepted:
        df = pd.DataFrame(accepted)
        books = df[df["record_type"] == "booking"]
        if len(books):
            st.write_df(
                "curated",
                "loan_bookings",
                books.assign(feed_file=rel, ingested_at=now).reindex(columns=BOOKING_COLUMNS),
                mode="append",
            )
        perf = df[df["record_type"].isin(["status", "correction"])].assign(feed_file=rel, ingested_at=now)
        if len(perf):
            perf = perf.reindex(columns=HISTORY_COLUMNS)
            restated = _record_restatements(perf[perf["record_type"] == "correction"], rel, now)
            st.write_df("curated", "loan_performance_history", _typed(perf), mode="append")
            rebuild_current()
    row = {
        "feed_file": rel,
        "file_month": file_month,
        "status": status,
        "records": total,
        "accepted": len(accepted) if status == "ingested" else 0,
        "quarantined": len(quarantined),
        "quarantined_share": round(share, 4),
        "restatements": restated,
        "ingested_at": now,
        "released_by": released_by,
    }
    st.write_df("ops", "feed_files", pd.DataFrame([row]), mode="append")
    if status == "held":
        alert = {
            "kind": "feed_held",
            "subject": rel,
            "value": share,
            "severity": "high",
            "ts": now,
            "definition_version": "",
        }
        st.write_df("ops", "alerts", pd.DataFrame([alert]), mode="append")
    verb = "ingested" if status == "ingested" else f"HELD ({share:.1%} quarantined, limit {limit:.0%})"
    log(f"feed {rel}: {verb}; {row['accepted']} accepted, {len(quarantined)} quarantined, {restated} restatements")
    return row


def _typed(perf: pd.DataFrame) -> pd.DataFrame:
    out = perf.copy()
    for c in ("dpd", "record_seq", *FLAGS):
        out[c] = pd.to_numeric(out[c]).astype("int64")
    for c in ("balance", "past_due_amount", "payment_amount", "scheduled_payment"):
        out[c] = pd.to_numeric(out[c]).astype("float64")
    return out


def _record_restatements(corrections: pd.DataFrame, rel: str, now: datetime) -> int:
    if corrections.empty:
        return 0
    before = _current_known(corrections)
    if before.empty:
        return 0
    m = corrections.merge(before, on=KEY, suffixes=("", "_before"))
    changed = []
    for r in m.to_dict("records"):
        diffs = {f: (r[f"{f}_before"], r[f]) for f in ("status", "dpd", "past_due_amount") if r[f"{f}_before"] != r[f]}
        if diffs:
            changed.append(
                {
                    "loan_id": r["loan_id"],
                    "period_month": r["period_month"],
                    "reported_month": r["reported_month"],
                    "feed_file": rel,
                    "changes_json": json.dumps(
                        {k: {"before": _jsonable(a), "after": _jsonable(b)} for k, (a, b) in diffs.items()}
                    ),
                    "dpd_before": int(r["dpd_before"]),
                    "dpd_after": int(r["dpd"]),
                    "ingested_at": now,
                }
            )
    if changed:
        get_store("harness").write_df("ops", "feed_restatements", pd.DataFrame(changed), mode="append")
    return len(changed)


def _jsonable(v):
    return v.item() if isinstance(v, np.generic) else v


def rebuild_current() -> int:
    """curated.loan_performance_current: the latest report for every loan-month (later reported month wins), and
    ops.feed_summary, the monthly aggregates the console may read."""
    st = get_store("harness")
    h = st.query(f"SELECT * FROM {st.fq('curated', 'loan_performance_history')}")
    cur = h.sort_values(["reported_month", "ingested_at", "record_seq"]).drop_duplicates(KEY, keep="last")
    st.write_df("curated", "loan_performance_current", cur.reset_index(drop=True), mode="overwrite")
    st.write_df("ops", "feed_summary", book_summary(cur), mode="overwrite")
    return len(cur)


def book_summary(cur: pd.DataFrame) -> pd.DataFrame:
    """Per reported period: loans reporting by status and delinquency bucket, balance, new bookings (no loan rows)."""
    st = get_store("harness")
    books = (
        st.query(f"SELECT booked_month, count(*) AS n FROM {st.fq('curated', 'loan_bookings')} GROUP BY booked_month")
        if st.table_exists("curated", "loan_bookings")
        else pd.DataFrame(columns=["booked_month", "n"])
    )
    new = dict(zip(books["booked_month"].astype(str), books["n"].astype(int), strict=True))
    rows = []
    for period, g in cur.groupby("period_month"):
        s, d = g["status"], g["dpd"].astype(int)
        rows.append(
            {
                "period_month": str(period),
                "loans_reporting": len(g),
                "current": int((s == "current").sum()),
                "dpd_30": int(((s == "delinquent") & (d == 30)).sum()),
                "dpd_60": int(((s == "delinquent") & (d == 60)).sum()),
                "dpd_90_plus": int(((s == "delinquent") & (d >= 90)).sum()),
                "forbearance": int((s == "forbearance").sum()),
                "paid_off": int((s == "paid_off").sum()),
                "charged_off": int((s == "charged_off").sum()),
                "other_terminal": int(s.isin(["bankrupt", "settled", "fraud", "deceased"]).sum()),
                "balance_outstanding": float(g["balance"].sum()),
                "new_bookings": int(new.get(str(period), 0)),
            }
        )
    cols = [
        "period_month",
        "loans_reporting",
        "current",
        "dpd_30",
        "dpd_60",
        "dpd_90_plus",
        "forbearance",
        "paid_off",
        "charged_off",
        "other_terminal",
        "balance_outstanding",
        "new_bookings",
    ]
    return pd.DataFrame(rows, columns=cols).sort_values("period_month").reset_index(drop=True)


def as_known_at(reported_month: str) -> pd.DataFrame:
    """The performance history as it was known at the end of `reported_month` (transaction time)."""
    st = get_store("harness")
    h = st.query(
        f"SELECT * FROM {st.fq('curated', 'loan_performance_history')} WHERE reported_month <= '{reported_month}'"
    )
    return h.sort_values(["reported_month", "ingested_at", "record_seq"]).drop_duplicates(KEY, keep="last")


def ingest(log=print) -> dict:
    files = pending_files()
    rows = [ingest_file(f, log) for f in files]
    if not files:
        log("feed: no new files")
    return {
        "files": len(rows),
        "held": [r["feed_file"] for r in rows if r["status"] == "held"],
        "accepted": int(sum(r["accepted"] for r in rows)),
        "quarantined": int(sum(r["quarantined"] for r in rows)),
        "restatements": int(sum(r["restatements"] for r in rows)),
    }
