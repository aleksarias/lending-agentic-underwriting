"""Shadow-first rollouts: a promoted champion scores live traffic in shadow before it decides anything.

A rollout's state is its latest event in production.rollouts (written by the promoter identity):
  shadow       started by the promotion: the champion scores every decision next to what serves and decides nothing
  serving      `lau rollout serve`: after the shadow report and the required approvals (ops.rollout_approvals,
               `approvals.rollout` different people), the serving alias moves to this champion
  retired      a later rollout started serving (this one can come back through that rollout's rollback)
  rolled_back  `lau rollout rollback`: serving returns to the model that served before (or to the legacy policy)
  superseded   a newer promotion started its own rollout while this one was still in shadow
Rollback needs one person: reducing risk never waits for a second approver. Every change rebuilds the decision model
(and updates the endpoint when it exists), so what serves always matches the registry.
"""

from __future__ import annotations

import getpass
import uuid
from datetime import UTC, datetime

import pandas as pd

from lau.modeling import registry_io
from lau.store import get_store


class RolloutError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _esc(v: str) -> str:
    return str(v).replace("'", "''")


def events(st=None) -> pd.DataFrame:
    st = st or get_store("harness")
    if not st.table_exists("production", "rollouts"):
        return pd.DataFrame()
    return st.query(f"SELECT * FROM {st.fq('production', 'rollouts')} ORDER BY ts")


def rollouts(st=None) -> list[dict]:
    """Every rollout with its current state and when it started, newest first."""
    ev = events(st)
    if ev.empty:
        return []
    out = []
    for rid, g in ev.groupby("rollout_id", sort=False):
        last, first = g.iloc[-1], g.iloc[0]
        served = g[g["event"] == "served"]
        out.append(
            {
                "rollout_id": str(rid),
                "state": str(last["state"]),
                "model_version": str(first["model_version"]),
                "definition_version": str(first["definition_version"]),
                "promotion_id": first.get("promotion_id"),
                "started_at": first["ts"],
                "started_by": str(first["by_user"]),
                "updated_at": last["ts"],
                "previous_serving_version": (
                    None
                    if served.empty or pd.isna(served.iloc[-1]["previous_serving_version"])
                    else str(served.iloc[-1]["previous_serving_version"])
                ),
                "events": g[["event", "state", "ts", "by_user", "note"]].to_dict("records"),
            }
        )
    return sorted(out, key=lambda r: pd.Timestamp(r["started_at"]), reverse=True)


def get(rollout_id: str) -> dict | None:
    return next((r for r in rollouts() if r["rollout_id"] == rollout_id), None)


def in_state(state: str) -> dict | None:
    return next((r for r in rollouts() if r["state"] == state), None)


def shadow_version() -> str | None:
    r = in_state("shadow")
    return r["model_version"] if r else None


def _event(r: dict, event: str, state: str, by: str, note: str = "", previous: str | None = None) -> None:
    row = {
        "rollout_id": r["rollout_id"],
        "event": event,
        "state": state,
        "ts": _now(),
        "by_user": by,
        "model_version": str(r["model_version"]),
        "definition_version": str(r["definition_version"]),
        "promotion_id": r.get("promotion_id"),
        "previous_serving_version": previous,
        "note": note[:2000],
    }
    get_store("promoter").write_df("production", "rollouts", pd.DataFrame([row]), mode="append")


def start(model_version: str, definition_version: str, promotion_id: str | None, by: str | None = None) -> dict:
    """Called by the promotion (as the promoter): the new champion starts in shadow."""
    by = by or getpass.getuser()
    current = in_state("shadow")
    if current is not None:
        _event(current, "superseded", "superseded", by, f"superseded by the promotion of v{model_version}")
    r = {
        "rollout_id": f"ro-{uuid.uuid4().hex[:10]}",
        "model_version": str(model_version),
        "definition_version": definition_version,
        "promotion_id": promotion_id,
    }
    _event(r, "started", "shadow", by, "promoted champion scores in shadow; it decides nothing yet")
    return r


# ---- evidence for the decision: what the shadow model would have done -----------------------------------------------
def _utc_literal(ts) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return f"TIMESTAMP '{t.isoformat(sep=' ')}'"


def shadow_decisions(r: dict, st=None) -> pd.DataFrame:
    """Live decisions this rollout's champion scored in shadow, since this rollout started (not an earlier one)."""
    st = st or get_store("harness")
    if not st.table_exists("ops", "decisions"):
        return pd.DataFrame()
    return st.query(
        "SELECT decision, path, probability_of_default, shadow_decision, shadow_probability_of_default, "
        f"fallback_used FROM {st.fq('ops', 'decisions')} "
        f"WHERE shadow_model_version = '{_esc(r['model_version'])}' AND NOT is_test "
        f"AND decided_at >= {_utc_literal(r['started_at'])}"
    )


def report(rollout_id: str, st=None) -> dict:
    """Shadow report: serving decisions next to what the shadow champion would have decided on the same traffic."""
    r = next((x for x in rollouts(st) if x["rollout_id"] == rollout_id), None)
    if r is None:
        raise RolloutError(f"unknown rollout {rollout_id}")
    df = shadow_decisions(r, st)
    n = len(df)
    if n == 0:
        return {"rollout_id": rollout_id, "n": 0, "model_version": r["model_version"]}

    def share(col: str, value: str) -> float:
        return round(float((df[col] == value).mean()), 4)

    both = df[df["probability_of_default"].notna() & df["shadow_probability_of_default"].notna()]
    return {
        "rollout_id": rollout_id,
        "model_version": r["model_version"],
        "n": n,
        "agreement": round(float((df["decision"] == df["shadow_decision"]).mean()), 4),
        "serving": {k: share("decision", k) for k in ("approve", "refer", "decline")},
        "shadow": {k: share("shadow_decision", k) for k in ("approve", "refer", "decline")},
        "approve_to_decline": int(((df["decision"] == "approve") & (df["shadow_decision"] == "decline")).sum()),
        "decline_to_approve": int(((df["decision"] == "decline") & (df["shadow_decision"] == "approve")).sum()),
        "mean_pd_serving": round(float(both["probability_of_default"].mean()), 5) if len(both) else None,
        "mean_pd_shadow": round(float(both["shadow_probability_of_default"].mean()), 5) if len(both) else None,
        "fallback_share": round(float(df["fallback_used"].astype(bool).mean()), 4),
    }


# ---- approvals -------------------------------------------------------------------------------------------------------
def decisions_recorded(rollout_id: str, st=None) -> list[dict]:
    st = st or get_store("harness")
    if not st.table_exists("ops", "rollout_approvals"):
        return []
    df = st.query(
        f"SELECT approval_id, approver, decision, note, ts FROM {st.fq('ops', 'rollout_approvals')} "
        f"WHERE rollout_id = '{_esc(rollout_id)}' ORDER BY ts"
    )
    return df.to_dict("records") if len(df) else []


def record_decision(rollout_id: str, decision: str, approver: str | None = None, note: str = "") -> dict:
    from lau.governance.approvals import ApprovalError, required, tally

    if decision not in ("approve", "reject"):
        raise ApprovalError("decision must be approve or reject")
    r = get(rollout_id)
    if r is None or r["state"] != "shadow":
        raise RolloutError(f"{rollout_id} is not in shadow; only a rollout in shadow can be approved to serve")
    approver = approver or getpass.getuser()
    if approver in {str(d["approver"]) for d in decisions_recorded(rollout_id)}:
        raise ApprovalError(f"{approver} already recorded a decision on {rollout_id}")
    row = {
        "approval_id": f"roapr-{uuid.uuid4().hex[:10]}",
        "rollout_id": rollout_id,
        "approver": approver,
        "decision": decision,
        "note": note[:2000],
        "ts": _now(),
    }
    get_store("harness").write_df("ops", "rollout_approvals", pd.DataFrame([row]), mode="append")
    t = tally(decisions_recorded(rollout_id))
    return {**row, "approvals": t["count"], "required": required("rollout"), "rejected_by": t["rejected_by"]}


# ---- serve / rollback ------------------------------------------------------------------------------------------------
def _set_serving(version: str | None) -> None:
    prod = registry_io.production_model_name()
    with registry_io.mlflow_session("promoter") as c:
        if version is None:
            try:
                c.delete_registered_model_alias(prod, registry_io.SERVING_ALIAS)
            except Exception:  # noqa: BLE001, S110 - nothing was serving
                pass
        else:
            c.set_registered_model_alias(prod, registry_io.SERVING_ALIAS, version)


def _serving_version() -> str | None:
    s = registry_io.serving_model("promoter")
    return str(s["model_version"]) if s else None


def _after_change(log=print) -> dict:
    """Rebuild the decision model (and update the endpoint), refresh evidence and the console snapshot."""
    from lau.decision import build
    from lau.promotion.promote import _after_promotion

    try:
        result = build.publish(log=log)
    except Exception as e:  # noqa: BLE001 - the registry change stands; `lau decision status` shows the gap
        result = {"published": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        log(f"warning: the decision model was not rebuilt ({result['error']}); run `lau decision build`")
    _after_promotion(log, rebuild=False)
    return result


def serve(rollout_id: str, by: str | None = None, log=print) -> dict:
    from lau.governance.approvals import required, tally
    from lau.settings import get_settings

    by = by or getpass.getuser()
    r = get(rollout_id)
    if r is None or r["state"] != "shadow":
        raise RolloutError(f"{rollout_id} is not in shadow")
    n = len(shadow_decisions(r))
    need_n = int(get_settings().decisioning.get("rollout", {}).get("min_shadow_decisions", 0))
    if n < need_n:
        raise RolloutError(f"{n} shadow decisions so far; serving needs at least {need_n} (see the shadow report)")
    t = tally(decisions_recorded(rollout_id))
    if t["rejected_by"]:
        raise RolloutError(f"rejected by {', '.join(t['rejected_by'])}")
    need = required("rollout")
    if t["count"] < need:
        raise RolloutError(
            f"{t['count']} of {need} required approvals; record them with `lau rollout decide {rollout_id}`"
        )
    previous = _serving_version()
    _set_serving(r["model_version"])
    _event(r, "served", "serving", by, f"approved by {', '.join(t['approvers'])}", previous=previous)
    for other in rollouts():
        if other["state"] == "serving" and other["rollout_id"] != rollout_id:
            _event(other, "retired", "retired", by, f"replaced by {rollout_id}")
    log(f"{rollout_id}: v{r['model_version']} now serves (previously {('v' + previous) if previous else 'legacy'})")
    return {"rollout_id": rollout_id, "serving": r["model_version"], "previous": previous, **_after_change(log)}


def rollback(rollout_id: str, reason: str, by: str | None = None, log=print) -> dict:
    by = by or getpass.getuser()
    r = get(rollout_id)
    if r is None or r["state"] != "serving":
        raise RolloutError(f"{rollout_id} is not serving; only the serving rollout can be rolled back")
    if not reason.strip():
        raise RolloutError("a rollback needs a reason")
    previous = r["previous_serving_version"]
    _set_serving(previous)
    _event(r, "rolled_back", "rolled_back", by, reason)
    if previous is not None:
        back = next(
            (o for o in rollouts() if o["state"] == "retired" and o["model_version"] == previous),
            None,
        )
        if back is not None:
            _event(back, "restored", "serving", by, f"serving again after the rollback of {rollout_id}")
    log(f"{rollout_id} rolled back: {('v' + previous) if previous else 'the legacy policy'} serves again")
    return {"rollout_id": rollout_id, "serving": previous, **_after_change(log)}
