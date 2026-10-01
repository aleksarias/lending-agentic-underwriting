"""Dated reports generated from the evidence tables (deterministic text, no LLM), stored with the agents' reports in
experiments.reports so the console lists them and they can leave the system for audit:

  monthly_report       `lau report monthly [--month YYYY-MM]`: improvement verdict, cycles and cost, decisions,
                       rollouts, production evidence, fairness on decisions, the loan feed, alerts, open items.
                       The daily job writes last month's on the first run of a month.
  model_documentation  `lau report model <production version>`: what the model is, its data and features, how it
                       was validated and approved, how it performs in production, its adverse-action reasons,
                       fairness, limitations and monitoring. A draft for model validation, not a validation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd

from lau.store import get_store


def _st():
    return get_store("harness")


def _q(sql: str) -> pd.DataFrame:
    try:
        return _st().query(sql)
    except Exception:  # noqa: BLE001 - a section whose table does not exist yet is reported as such
        return pd.DataFrame()


def _t(key: str, table: str) -> str | None:
    st = _st()
    return st.fq(key, table) if st.table_exists(key, table) else None


def _pct(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{float(v) * 100:.1f}%"


def _num(v, digits: int = 0) -> str:
    return "—" if v is None or pd.isna(v) else f"{float(v):,.{digits}f}"


def _s(v, default: str = "—") -> str:
    return default if v is None or (isinstance(v, float) and pd.isna(v)) or str(v) in ("", "nan", "None") else str(v)


def _table(df: pd.DataFrame, cols: dict[str, str]) -> str:
    if df.empty:
        return "_none_"
    head = "| " + " | ".join(cols.values()) + " |\n|" + "---|" * len(cols)
    rows = ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in df.to_dict("records")]
    return head + "\n" + "\n".join(rows)


def _latest_run(table: str) -> pd.DataFrame:
    t = _t("ops", table)
    if not t:
        return pd.DataFrame()
    return _q(f"SELECT * FROM {t} WHERE run_id = (SELECT run_id FROM {t} ORDER BY computed_at DESC LIMIT 1)")


def _store(
    report_id: str, kind: str, title: str, body: str, definition_version: str = "", ref: str | None = None
) -> str:
    st = _st()
    if st.table_exists("experiments", "reports"):
        st.execute(f"DELETE FROM {st.fq('experiments', 'reports')} WHERE report_id = '{report_id}'")
    row = {
        "report_id": report_id,
        "cycle_id": None,
        "definition_version": definition_version,
        "author": "lau reports",
        "kind": kind,
        "title": title,
        "body": body,
        "candidate_ref": ref,
        "verdict": None,
        "created_at": datetime.now(UTC),
    }
    st.write_df("experiments", "reports", pd.DataFrame([row]), mode="append")
    return report_id


# ---- monthly report ---------------------------------------------------------------------------------------------------
def monthly(month: str | None = None, log=print) -> str:
    """The improvement report for a calendar month (default: last month)."""
    m = pd.Period(month, "M") if month else pd.Period(datetime.now(UTC).strftime("%Y-%m"), "M") - 1
    lo, hi = m.start_time.strftime("%Y-%m-%d"), (m + 1).start_time.strftime("%Y-%m-%d")
    within = f"BETWEEN TIMESTAMP '{lo} 00:00:00' AND TIMESTAMP '{hi} 00:00:00'"
    out = [
        f"# Monthly improvement report: {m}",
        "",
        f"_Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC from the evidence tables. Synthetic data._",
        "",
    ]

    ledger = _latest_run("improvement_ledger")
    out += ["## Is it improving?", ""]
    if ledger.empty:
        out += ["No evidence has been computed yet.", ""]
    else:
        r = ledger.iloc[0]
        lift = (
            f" Estimated AUC lift over the legacy policy {_num(r['lift_estimate'], 3)} ({_num(r['lift_lo'], 3)} to {_num(r['lift_hi'], 3)})."
            if pd.notna(r.get("lift_estimate"))
            else ""
        )
        out += [
            f"**{r['title']}.** {r['detail'] or ''}{lift}",
            "",
            f"Best known model: {_s(r['best_known_label'])}; serving: {_s(r['serving_key'], 'the legacy policy')}.",
            "",
        ]

    cyc = _t("ops", "cycles")
    out += ["## Improvement cycles", ""]
    cycles = (
        _q(f"SELECT cycle_id, status, started_at FROM {cyc} WHERE started_at {within} ORDER BY started_at")
        if cyc
        else pd.DataFrame()
    )
    cost = _t("ops", "cost_log")
    spend = _q(f"SELECT kind, sum(usd) AS usd FROM {cost} WHERE ts {within} GROUP BY kind") if cost else pd.DataFrame()
    total = float(spend["usd"].sum()) if len(spend) else 0.0
    out += [
        f"{len(cycles)} cycle(s) ran; logged spend ${total:,.2f}.",
        "",
        _table(cycles, {"cycle_id": "Cycle", "status": "Outcome", "started_at": "Started"}),
        "",
    ]
    ev = _t("ops", "evaluations")
    evals = _q(f"SELECT count(*) AS n FROM {ev} WHERE ts {within}") if ev else pd.DataFrame()
    gates = _t("ops", "gate_results")
    gate = (
        _q(f"SELECT candidate_ref, passed, ts FROM {gates} WHERE ts {within} ORDER BY ts") if gates else pd.DataFrame()
    )
    out += [f"Harness evaluations: {int(evals['n'].iloc[0]) if len(evals) else 0}; holdout gate runs: {len(gate)}.", ""]
    if len(gate):
        out += [_table(gate, {"candidate_ref": "Candidate", "passed": "Passed", "ts": "When"}), ""]

    dec = _t("ops", "decisions")
    out += ["## Decisions", ""]
    if not dec:
        out += ["No decision has been made yet.", ""]
    else:
        d = _q(
            "SELECT count(*) AS n, avg(CASE WHEN decision = 'approve' THEN 1.0 ELSE 0.0 END) AS approve, "
            "avg(CASE WHEN decision = 'refer' THEN 1.0 ELSE 0.0 END) AS refer, "
            "avg(CASE WHEN decision = 'decline' THEN 1.0 ELSE 0.0 END) AS decline, "
            "avg(CASE WHEN fallback_used THEN 1.0 ELSE 0.0 END) AS fallback, "
            "sum(CASE WHEN reasons_missing THEN 1 ELSE 0 END) AS missing "
            f"FROM {dec} WHERE NOT is_test AND decided_at {within}"
        ).iloc[0]
        out += [
            f"{_num(d['n'])} decisions: {_pct(d['approve'])} approved, {_pct(d['refer'])} referred, {_pct(d['decline'])} declined; "
            f"{_pct(d['fallback'])} fell back to the legacy policy; {_num(d['missing'])} adverse decisions without reasons.",
            "",
        ]
        versions = _q(
            f"SELECT model_version, policy_version, count(*) AS n FROM {dec} WHERE NOT is_test AND decided_at {within} "
            "GROUP BY model_version, policy_version ORDER BY n DESC"
        )
        out += [
            _table(versions.fillna("legacy"), {"model_version": "Model", "policy_version": "Policy", "n": "Decisions"}),
            "",
        ]
    rc = _t("ops", "release_checks")
    if rc:
        checks = _q(f"SELECT * FROM {rc} WHERE run_at {within} ORDER BY run_at")  # `check` is a reserved word
        out += [
            f"Release checks this month: {len(checks)}.",
            "",
            _table(checks, {"check": "Check", "passed": "Passed", "run_at": "When"}),
            "",
        ]

    ro = _t("production", "rollouts")
    out += ["## Rollouts", ""]
    events = (
        _q(f"SELECT rollout_id, event, model_version, by_user, ts FROM {ro} WHERE ts {within} ORDER BY ts")
        if ro
        else pd.DataFrame()
    )
    out += [
        _table(
            events, {"rollout_id": "Rollout", "event": "Event", "model_version": "Model", "by_user": "By", "ts": "When"}
        ),
        "",
    ]

    pe = _latest_run("production_evidence")
    out += ["## Production evidence (matured loans)", ""]
    if pe.empty:
        out += ["No production loan has matured yet.", ""]
    else:
        o = pe[pe["scope"] == "overall"].iloc[0]
        out += [
            f"{_num(o['n_matured'])} of {_num(o['n_booked'])} booked loans matured (performance through {o['as_of_month']}): "
            f"realized default {_pct(o['realized_rate'])} against {_pct(o['predicted_pd'])} predicted; AUC among matured "
            f"loans {_num(o['auc'], 3)}.",
            "",
            _table(
                pe[pe["scope"] == "band"],
                {"key": "Band", "n_matured": "Matured", "predicted_pd": "Predicted", "realized_rate": "Realized"},
            ),
            "",
        ]

    fair = _latest_run("decision_fairness")
    out += ["## Fairness on actual decisions", ""]
    if fair.empty:
        out += ["No decisions to measure yet.", ""]
    else:
        f = fair[fair["method"] != "synthetic_truth"].copy()
        f["air"] = f["air"].map(lambda v: _num(v, 2))
        f["approval_rate"] = f["approval_rate"].map(_pct)
        flagged = int(fair["below_threshold"].astype(bool).sum())
        out += [
            f"{flagged} group(s) below the adverse impact threshold. Race and ethnicity are estimated (surname-based); see the method note in the console.",
            "",
            _table(
                f,
                {
                    "attribute": "Attribute",
                    "group": "Group",
                    "method": "Method",
                    "approval_rate": "Approved",
                    "air": "AIR",
                },
            ),
            "",
        ]

    out += ["## Loan status feed", ""]
    ff = _t("ops", "feed_files")
    files = (
        _q(f"SELECT feed_file, status, accepted, quarantined, restatements FROM {ff} WHERE ingested_at {within}")
        if ff
        else pd.DataFrame()
    )
    if files.empty:
        out += ["No feed file was read this month.", ""]
    else:
        out += [
            f"{len(files)} file(s): {int(files['accepted'].sum()):,} records accepted, {int(files['quarantined'].sum()):,} quarantined, "
            f"{int(files['restatements'].sum()):,} restatements; {int((files['status'] == 'held').sum())} held for review.",
            "",
        ]

    al = _t("ops", "alerts")
    out += ["## Alerts", ""]
    alerts = _q(f"SELECT kind, subject, severity, ts FROM {al} WHERE ts {within} ORDER BY ts") if al else pd.DataFrame()
    out += [_table(alerts, {"kind": "Kind", "subject": "Subject", "severity": "Severity", "ts": "Raised"}), ""]

    from lau.notify import open_items

    try:
        items = open_items()
    except Exception:  # noqa: BLE001 - the report is still useful without the open-items list
        items = []
    out += ["## Needs a person now", ""] + ([f"- {i}" for i in items] or ["Nothing."]) + [""]
    report_id = _store(f"mr-{m}", "monthly_report", f"Monthly improvement report {m}", "\n".join(out))
    log(f"monthly report {report_id} written ({len(out)} lines)")
    return report_id


def monthly_if_due(log=print) -> str | None:
    """Write last month's report once (the daily job calls this every day)."""
    m = pd.Period(datetime.now(UTC).strftime("%Y-%m"), "M") - 1
    t = _t("experiments", "reports")
    if t and len(_q(f"SELECT report_id FROM {t} WHERE report_id = 'mr-{m}'")):
        return None
    return monthly(str(m), log)


# ---- model documentation pack ------------------------------------------------------------------------------------------
def model_pack(production_version: str, log=print) -> str:
    """A documentation draft for one production model version (champion)."""
    from lau.decision.reasons import statement_for
    from lau.modeling import registry_io

    prod = registry_io.production_model_name()
    tags = registry_io.version_tags(prod, production_version, "harness")
    model = registry_io.load_pd_model(f"models:/{prod}/{production_version}", "harness")
    version = tags.get("definition_version", "")
    cand = tags.get("source_candidate_version")
    ref = f"candidate:{cand}" if cand else None
    out = [
        f"# Model documentation: {prod} v{production_version}",
        "",
        f"_Draft generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC from the registry and evidence tables. Synthetic data. "
        "Not a model validation: an independent validator reviews and signs off separately._",
        "",
        "## Identity",
        "",
        f"- Model type: {model.model_type}; parameters: `{json.dumps(model.params, default=str)[:400]}`",
        f"- Definition of default: `{version}`",
        f"- Source candidate: {cand or '—'}; gate: {tags.get('gate_id', '—')}; approval: {tags.get('approval_id', '—')}",
        f"- Status: {tags.get('status', '—')}",
        "",
        "## Purpose and use",
        "",
        "Estimates the probability that an approved personal loan defaults under the definition above. The credit policy "
        "(config/policy.yaml, separately approved) turns that probability into approve, refer or decline, with up to four "
        "principal reasons on adverse decisions. Agents proposed and trained it; the deterministic harness evaluated it; "
        "people approved its promotion.",
        "",
        "## Inputs and adverse-action reasons",
        "",
    ]
    feats = pd.DataFrame(
        [{"feature": f, "code": statement_for(f)[0], "statement": statement_for(f)[1]} for f in model.features]
    )
    out += [_table(feats, {"feature": "Input", "code": "Reason code", "statement": "Statement an applicant reads"}), ""]
    imp = model.feature_importance()
    top = pd.DataFrame([{"feature": k, "share": f"{v:.1%}"} for k, v in list(imp.items())[:12]])
    out += ["Relative importance (top 12):", "", _table(top, {"feature": "Input", "share": "Share"}), ""]

    out += ["## Validation (harness)", ""]
    ev = _t("ops", "evaluations")
    if ev and ref:
        e = _q(f"SELECT eval_id, ts, result_json FROM {ev} WHERE candidate_ref = '{ref}' ORDER BY ts DESC LIMIT 1")
        if len(e):
            res = json.loads(e["result_json"].iloc[0] or "{}")
            val = res.get("validation") or {}
            out += [
                f"Validation AUC {val.get('auc', '—')}, KS {val.get('ks', '—')}, calibration slope {val.get('calibration_slope', '—')} (evaluation {e['eval_id'].iloc[0]}).",
                "",
            ]
    gates = _t("ops", "gate_results")
    if gates and ref:
        g = _q(
            f"SELECT gate_id, passed, holdout_auc, reference_holdout_auc, ts FROM {gates} WHERE candidate_ref = '{ref}' ORDER BY ts"
        )
        out += [
            "Holdout gate results:",
            "",
            _table(
                g,
                {
                    "gate_id": "Gate",
                    "passed": "Passed",
                    "holdout_auc": "Holdout AUC",
                    "reference_holdout_auc": "Reference AUC",
                    "ts": "When",
                },
            ),
            "",
        ]
    bench = _latest_run("benchmark_results")
    if len(bench):
        mine = bench[(bench["model_version"].astype(str) == str(production_version)) & (bench["metric"] == "auc")]
        if len(mine):
            out += [
                "Benchmark (frozen windows):",
                "",
                _table(
                    mine, {"benchmark_key": "Benchmark", "value": "AUC", "ci_lo": "Low", "ci_hi": "High", "n": "Loans"}
                ),
                "",
            ]

    out += ["## Approvals", ""]
    ap = _t("ops", "approvals")
    if ap and ref:
        a = _q(f"SELECT approver, decision, rationale, ts FROM {ap} WHERE candidate_ref = '{ref}' ORDER BY ts")
        out += [_table(a, {"approver": "Approver", "decision": "Decision", "rationale": "Rationale", "ts": "When"}), ""]
    ro = _t("production", "rollouts")
    if ro:
        r = _q(
            f"SELECT rollout_id, event, by_user, note, ts FROM {ro} WHERE model_version = '{production_version}' ORDER BY ts"
        )
        out += [
            "Rollout events:",
            "",
            _table(r, {"rollout_id": "Rollout", "event": "Event", "by_user": "By", "note": "Note", "ts": "When"}),
            "",
        ]

    out += ["## Production performance", ""]
    pe = _latest_run("production_evidence")
    mine = pe[(pe["scope"] == "model") & (pe["key"].astype(str) == str(production_version))] if len(pe) else pe
    if mine.empty:
        out += ["No matured production loans decided by this model yet.", ""]
    else:
        o = mine.iloc[0]
        out += [
            f"{_num(o['n_matured'])} matured of {_num(o['n_booked'])} booked: realized {_pct(o['realized_rate'])} against {_pct(o['predicted_pd'])} predicted; AUC {_num(o['auc'], 3)}.",
            "",
        ]

    out += [
        "## Limitations",
        "",
        "- Trained and evaluated on synthetic data; every number here describes the synthetic world only.",
        "- Outcomes exist only for approved applications (legacy policy in training, the model's own approvals in production): "
        "selection bias is documented, not corrected (docs/reject-inference.md).",
        "- Group membership for fairness testing is estimated in production; the method needs counsel's approval.",
        "",
        "## Monitoring",
        "",
        "Daily: score and feature drift (PSI) against the definition's baseline, early delinquency on recent vintages, "
        "training-serving parity of inputs, the loan status feed's checks. On maturation: predicted against realized default "
        "(alert beyond the configured tolerance), production ranking quality, fairness on actual decisions.",
        "",
    ]
    report_id = _store(
        f"md-{production_version}",
        "model_documentation",
        f"Model documentation: production v{production_version}",
        "\n".join(out),
        version,
        ref,
    )
    log(f"model documentation {report_id} written")
    return report_id
