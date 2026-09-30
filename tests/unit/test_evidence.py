"""Evidence backend: benchmark ledger, sensitivity, vintages, cash-flow cohorts, proxy scan, registry, verdict."""

from __future__ import annotations

import pandas as pd
import pytest

VERDICTS = {"improved", "no_change", "not_best", "regressed", "insufficient_evidence"}
STATUSES = {"serving", "champion", "challenger", "candidate", "baseline", "retired", "superseded"}


@pytest.fixture(scope="module")
def evidence(lake):
    from lau.evidence.run import run_all
    from lau.store import get_store

    counts = run_all(log=lambda m: None)
    return {"counts": counts, "store": get_store("harness")}


def _read(st, table: str) -> pd.DataFrame:
    """A table as the latest evidence run wrote it (most tables are append-per-run; other tests run it too)."""
    from lau.evidence import schemas

    df = st.query(f"SELECT * FROM {st.fq('ops', table)}")
    if table not in schemas.OVERWRITE_TABLES and "run_id" in df.columns and len(df):
        df = df[df["run_id"] == df.sort_values("computed_at")["run_id"].iloc[-1]]
    return df


def test_run_all_writes_every_table_with_contract_columns(evidence):
    from lau.evidence import schemas

    st = evidence["store"]
    for table, n in evidence["counts"].items():
        assert n > 0, table
        want = {c for c, _ in schemas.TABLES[table]}
        cols = set(_read(st, table).columns)
        assert want <= cols, (table, want - cols)


def test_benchmark_has_reference_and_models_with_valid_intervals(evidence):
    b = _read(evidence["store"], "benchmark_results")
    auc = b[b["metric"] == "auc"]
    assert "legacy_score" in set(auc["model_key"])
    assert (auc["model_key"] != "legacy_score").any()
    assert auc["value"].between(0, 1).all()
    ok = auc.dropna(subset=["ci_lo", "ci_hi"])
    assert ((ok["ci_lo"] <= ok["value"] + 1e-9) & (ok["value"] <= ok["ci_hi"] + 1e-9)).all()
    # exactly one best model per benchmark for AUC
    assert (auc[auc["is_best"]].groupby("benchmark_key").size() == 1).all()
    # diffs against the frozen reference are present for every scored model
    diffs = b[b["metric"] == "auc_minus_reference"]
    assert set(diffs["model_key"]) == set(auc["model_key"]) - {"legacy_score"}


def test_definition_sensitivity_is_ordered_by_threshold(evidence):
    s = _read(evidence["store"], "definition_sensitivity")
    wide = s.pivot_table(index="period", columns="benchmark_dpd", values="default_rate")
    assert (wide[30] >= wide[60] - 1e-12).all() and (wide[60] >= wide[90] - 1e-12).all()


def test_vintage_curves_are_cumulative(evidence):
    v = _read(evidence["store"], "vintage_curves").sort_values(["cohort", "dpd_threshold", "mob"])
    for _, g in v.groupby(["cohort", "dpd_threshold"]):
        assert g["cum_rate"].is_monotonic_increasing
        assert list(g["mob"]) == list(range(1, 13))
    # a higher threshold never has a higher cumulative rate
    wide = v.pivot_table(index=["cohort", "mob"], columns="dpd_threshold", values="cum_rate")
    assert (wide[30] >= wide[60] - 1e-12).all() and (wide[60] >= wide[90] - 1e-12).all()


def test_cashflow_cohorts_are_aggregates(evidence):
    c = _read(evidence["store"], "cashflow_cohorts")
    assert (c["n"] > 0).all()
    assert c["nsf_rate"].between(0, 1).all() and c["overdraft_share"].between(0, 1).all()
    assert "application_id" not in c.columns


def test_proxy_scan_flags_the_planted_proxies(evidence):
    p = _read(evidence["store"], "proxy_scan")
    flagged = set(p.loc[p["flagged"], "feature"])
    assert "geo_affluence_idx" in flagged
    assert "cf_remittance_share_6m" in flagged  # caught only per group (Hispanic vs reference), not pooled
    assert {"pooled"} <= set(p["protected_group"])


def test_registry_sync_and_flattened_metrics(evidence):
    r = _read(evidence["store"], "model_registry")
    assert set(r["status"]) <= STATUSES and len(r) >= 1
    m = _read(evidence["store"], "evaluation_metrics")
    assert {"validation.auc", "required_margin"} <= set(m["metric"])


def test_verdict_is_a_known_code_with_evidence(evidence):
    v = _read(evidence["store"], "improvement_ledger").iloc[-1]
    assert v["verdict_code"] in VERDICTS
    assert v["title"] and v["detail"]
    import json

    den = json.loads(v["denominator_json"])
    assert {"tests_since_reset", "holdout_budget", "candidates"} <= set(den)


def test_latest_matured_months_skips_immature_and_holdout_months():
    from lau.evidence.benchmark import latest_matured_months

    months = [f"2024-{m:02d}" for m in range(1, 13)]
    # as of 2025-06 with 12 months of performance required: 2024-01..2024-06 are mature
    got = latest_matured_months(months, "2025-06", 12, [("2024-05", "2024-06")], n_months=5)
    assert got == ["2024-01", "2024-02", "2024-03", "2024-04"]
    # the run stops at a gap: 2024-03 sits in a holdout, so only the later consecutive run is used
    got = latest_matured_months(months, "2025-06", 12, [("2024-03", "2024-03")], n_months=5)
    assert got == ["2024-04", "2024-05", "2024-06"]
    assert latest_matured_months(months, "2024-06", 12, [], n_months=5) == []


def test_latest_matured_window_never_overlaps_a_holdout(evidence):
    from lau.evidence.benchmark import resolve_window
    from lau.evidence.config import load_benchmark_config
    from lau.evidence.context import EvidenceContext

    cfg = load_benchmark_config()
    cfg = cfg.model_copy(
        update={"window": cfg.window.model_copy(update={"policy": "latest_matured_excluding_holdout"})}
    )
    ctx = EvidenceContext(store=evidence["store"], cfg=cfg, log=lambda m: None)
    w = resolve_window(ctx)
    assert w.policy in {"latest_matured_excluding_holdout", "validation"}
    if w.policy == "latest_matured_excluding_holdout":
        for a, b in ctx.oot_ranges:
            assert all(not (a <= m <= b) for m in w.months), (w.months, a, b)


def test_evaluation_records_versions_and_best_known(evidence, lake):
    """Once the ledger exists, evaluations carry versions and a best-known comparison (or a skip reason)."""
    from lau.data.features import load_dev_frame
    from lau.harness.evaluate import evaluate_model
    from lau.modeling.model import PDModel
    from lau.modeling.search_space import defaults

    dev = load_dev_frame(evidence["store"], lake["version"], "test")
    tr = dev[dev["split"] == "train"]
    m = PDModel("logreg", defaults("logreg"), ["bureau_score", "dti", "pmt_to_income"], [], lake["version"]).fit(
        tr, tr["label"].to_numpy()
    )
    ev = evaluate_model(m, lake["version"], "test:evidence", count_test=False)
    assert ev["versions"]["definition_version"] == lake["version"]
    assert ev["versions"]["data_version"]
    bk = ev["best_known"]
    assert ("auc" in bk and "beats_best_known" in ev["checks"]) or "skipped" in bk
