"""Synthetic origination: one simulated month of new applications per run, each sent for a decision.

The simulated clock (ops.sim_clock) starts the month after the data's as-of month and moves forward one month per
successful run. Applications for a month come from the same generator as the training data, seeded by the month,
so a retried run sends identical requests (same request ids, so the same decision ids). Each request carries the
applicant's bank-statement lines from before the decision. The applicants' latent risk, protected attributes and
surname go to simulation.truth (harness only) for the servicer simulator and fairness checks; they never reach a
model, a request, an agent or the console.

Transports: `endpoint` (Model Serving, when it exists) or `inprocess` (the live decision model loaded from the
registry: the same artifact the endpoint serves). `auto` picks the endpoint when it exists.
"""

from __future__ import annotations

import time
import zlib
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.decision import log as decision_log
from lau.decision.pyfunc import to_request_row
from lau.settings import get_settings
from lau.store import get_store

REQUEST_FIELDS_EXCLUDED = {"origination_month"}  # bookkeeping of the generator, not something an applicant sends


class NoDecisionModelError(RuntimeError):
    pass


# ---- the simulated clock --------------------------------------------------------------------------------------------
def current_month() -> pd.Period:
    st = get_store("harness")
    if st.table_exists("ops", "sim_clock"):
        df = st.query(f"SELECT sim_month FROM {st.fq('ops', 'sim_clock')} ORDER BY advanced_at DESC LIMIT 1")
        if len(df):
            return pd.Period(str(df["sim_month"].iloc[0]), "M")
    return pd.Period(get_settings().synth["as_of_month"], "M") + 1


def _advance(month: pd.Period) -> None:
    row = {"sim_month": str(month + 1), "advanced_at": datetime.now(UTC).replace(tzinfo=None), "from_month": str(month)}
    get_store("harness").write_df("ops", "sim_clock", pd.DataFrame([row]), mode="append")


# ---- applications --------------------------------------------------------------------------------------------------
def generate_month(month: pd.Period, n: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(applications, pre-decision statement lines, truth) for one simulated month; deterministic."""
    from lau.synth import cashflow as cf
    from lau.synth import surnames
    from lau.synth.generator import PII_COLUMNS, PROTECTED_COLUMNS, _applications

    s = get_settings().synth
    seed = int(s["seed"]) + zlib.crc32(f"traffic-{month}".encode()) % 1_000_000
    prefix = f"M{month.year % 100:02d}{month.month:02d}"
    apps, risk, protected, lat = _applications(
        np.random.default_rng(seed),
        int(n),
        [month],
        pd.Period(s["drift_start_month"], "M"),
        int(s["n_noise_numeric"]),
        prefix,
        s["cashflow"],
    )
    tx = cf.simulate_transactions(
        np.random.default_rng(seed + 1),
        apps["application_id"].to_numpy(),
        apps["decision_ts"],
        lat,
        int(s["cashflow"]["months_history"]),
        np.zeros(len(apps)),
    )
    race = protected["race_ethnicity"].to_numpy()
    truth = pd.DataFrame(
        {
            "application_id": apps["application_id"],
            "sim_month": str(month),
            "latent_risk": risk,
            "race_ethnicity": race,
            "sex": protected["sex"].to_numpy(),
            "age": protected["age"].to_numpy(),
            "surname": surnames.draw(np.random.default_rng(seed + 3), race),  # informative, unlike the generator's
            "zip3": apps["zip3"].to_numpy(),
        }
    )
    apps = apps.drop(columns=[c for c in PII_COLUMNS + PROTECTED_COLUMNS if c in apps.columns])
    return apps, tx[tx["days_before_decision"] >= 1], truth


def build_requests(apps: pd.DataFrame, tx: pd.DataFrame, prefix: str = "rq-") -> list[dict]:
    lines = {
        aid: g[["txn_date", "amount", "balance_after", "category"]].assign(txn_date=lambda d: d["txn_date"].astype(str))
        for aid, g in tx.groupby("application_id")
    }
    out = []
    for app in apps.to_dict("records"):
        aid = str(app["application_id"])
        fields = {k: _plain(v) for k, v in app.items() if k not in REQUEST_FIELDS_EXCLUDED and not k.startswith("cf_")}
        out.append(
            {
                "request_id": f"{prefix}{aid}",
                "application": fields,
                "transactions": lines[aid].to_dict("records") if aid in lines else [],
                "decision_date": pd.Timestamp(app["decision_ts"]).date().isoformat(),
            }
        )
    return out


def _plain(v):
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


# ---- transports ------------------------------------------------------------------------------------------------------
class InProcess:
    name = "inprocess"

    def __init__(self) -> None:
        from lau.decision.build import load_live

        self.model = load_live()
        if self.model is None:
            raise NoDecisionModelError("no decision model is live: approve a policy, then `lau decision build`")

    def decide(self, rows: list[dict]) -> list[dict]:
        out = self.model.predict(None, pd.DataFrame(rows))
        return out.astype(object).where(out.notna(), None).to_dict("records")


class Endpoint:
    name = "endpoint"

    def __init__(self, warmup_s: int = 900) -> None:
        from lau.decision.build import _endpoint_cfg, _workspace

        self.w = _workspace("harness")
        self.endpoint = _endpoint_cfg()["name"]
        self.warmup_s = warmup_s

    def decide(self, rows: list[dict]) -> list[dict]:
        """Retries while a scaled-to-zero endpoint starts (503/504) for up to warmup_s seconds."""
        deadline, wait = time.monotonic() + self.warmup_s, 5.0
        while True:
            try:
                return list(self.w.serving_endpoints.query(name=self.endpoint, dataframe_records=rows).predictions)
            except Exception as e:  # noqa: BLE001 - retry only what a cold start looks like
                cold = any(code in str(e) for code in ("503", "504", "UNAVAILABLE", "scaling", "Timeout"))
                if not cold or time.monotonic() > deadline:
                    raise
                time.sleep(wait)
                wait = min(wait * 1.5, 30.0)


def transport(kind: str = "auto"):
    if kind == "inprocess":
        return InProcess()
    if kind == "endpoint":
        return Endpoint()
    from lau.decision.build import endpoint_state

    return Endpoint() if endpoint_state().get("exists") else InProcess()


def send(requests: list[dict], via, batch_size: int) -> tuple[list[dict], list[dict], list[float]]:
    """(responses, request rows, client latency per response) in request order."""
    responses, rows_sent, latency = [], [], []
    for i in range(0, len(requests), batch_size):
        rows = [to_request_row(r) for r in requests[i : i + batch_size]]
        t0 = time.perf_counter()
        resp = via.decide(rows)
        per = (time.perf_counter() - t0) * 1000 / max(len(rows), 1)
        responses += resp
        rows_sent += rows
        latency += [round(per, 2)] * len(resp)
    return responses, rows_sent, latency


def originate(months: int | None = None, kind: str = "auto", log=print) -> dict:
    """Send the next simulated month(s) of applications for decisions and log every decision."""
    cfg = get_settings().decisioning["traffic"]
    months = int(months or cfg["months_per_run"])
    via = transport(kind)
    st = get_store("harness")
    summary = []
    for _ in range(months):
        month = current_month()
        apps, tx, truth = generate_month(month, int(cfg["applications_per_month"]))
        requests = build_requests(apps, tx)
        t0 = time.perf_counter()
        responses, rows, latency = send(requests, via, int(cfg["batch_size"]))
        n_new = decision_log.record(responses, rows, source=via.name, client_latency_ms=latency)
        st.write_df("simulation", "truth", truth, mode="replace_partition", partition={"sim_month": str(month)})
        sent = pd.DataFrame(
            {
                "request_id": [r["request_id"] for r in requests],
                "application_id": apps["application_id"].astype(str).to_numpy(),
                "sim_month": str(month),
                "sent_at": datetime.now(UTC).replace(tzinfo=None),
                "transport": via.name,
            }
        )
        st.write_df("ops", "originations", sent, mode="replace_partition", partition={"sim_month": str(month)})
        _advance(month)
        mix = pd.Series([r["decision"] for r in responses]).value_counts().to_dict()
        took = round(time.perf_counter() - t0, 1)
        log(f"{month}: {len(responses)} decisions via {via.name} in {took}s ({n_new} new in the log) {mix}")
        summary.append({"month": str(month), "decisions": len(responses), "new": n_new, "mix": mix, "seconds": took})
    return {"transport": via.name, "months": summary}
