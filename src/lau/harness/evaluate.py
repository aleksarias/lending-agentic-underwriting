"""Deterministic candidate evaluation on the VALIDATION split (no holdout here).

Computes AUC/KS, calibration, lift, stability across time slices and segments, PSI, thin-file performance,
leakage, fairness (adverse impact + proxies), reason-code quality, and the comparison to the reference: the
champion OF THE SAME definition version, else the version's baseline. Each counted evaluation increments the
multiple-testing ledger. Results go to ops.evaluations (and the candidate's MLflow run).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.data.features import apply_features, load_dev_frame, prohibited_features
from lau.data.splits import read_split_meta
from lau.harness import fairness, leakage, metrics, multiple_testing, reason_codes
from lau.modeling.registry_io import DefinitionMismatchError, champion_for
from lau.settings import get_settings
from lau.store import get_store

SEGMENTS = ["channel", "product", "thin_file", "employment_type"]
MIN_SEG_N, MIN_SEG_BAD = 300, 15


def window_population(store, start: str, end: str) -> pd.DataFrame:
    """Through-the-door applications (approved + declined) originated in [start, end]."""
    return store.query(
        f"SELECT * FROM {store.fq('curated', 'applications')} "
        f"WHERE origination_month >= '{start}' AND origination_month <= '{end}'"
    )


def _segment_aucs(df: pd.DataFrame, p: np.ndarray) -> dict[str, float]:
    out = {}
    for seg in SEGMENTS:
        if seg not in df:
            continue
        for val, idx in df.groupby(df[seg].astype(str)).groups.items():
            y = df.loc[idx, "label"].to_numpy()
            if len(y) >= MIN_SEG_N and y.sum() >= MIN_SEG_BAD:
                out[f"{seg}={val}"] = metrics.auc(y, p[df.index.get_indexer(idx)])
    return out


def _slice_aucs(df: pd.DataFrame, p: np.ndarray, n_slices: int = 3) -> dict[str, float]:
    months = sorted(df["origination_month"].unique())
    chunks = np.array_split(np.array(months), min(n_slices, len(months)))
    out = {}
    for ch in chunks:
        m = df["origination_month"].isin(ch).to_numpy()
        if m.sum() >= MIN_SEG_N and df.loc[m, "label"].sum() >= MIN_SEG_BAD:
            out[f"{ch[0]}..{ch[-1]}"] = metrics.auc(df.loc[m, "label"].to_numpy(), p[m])
    return out


def catalog_lookup(store, version: str) -> pd.DataFrame:
    return store.query(f"SELECT * FROM {store.fq('curated', 'data_catalog')} WHERE definition_version = '{version}'")


def feature_leakage(model, dev_train: pd.DataFrame, cat: pd.DataFrame, cfg: dict) -> list[dict]:
    """Leakage per model input. Engineered features inherit the worst risk of their source columns."""
    lineage = {r["variable"]: {"available_at": r.get("availability")} for r in cat.to_dict("records")}
    base_risk = dict(zip(cat["variable"], cat["leakage_risk"], strict=False))
    y = dev_train["label"].to_numpy()
    frame = apply_features(dev_train, [s for s in model.engineered if s.name not in dev_train])
    out = []
    eng = {s.name: s for s in model.engineered}
    for f in model.features:
        finding = leakage.check_column(frame, f, y, cfg, lineage.get(f)).as_dict()
        if f in eng:
            srcs = list(eng[f].source_columns)
            inherited = [s for s in srcs if base_risk.get(s) == "high"]
            if inherited:
                finding["risk"] = "high"
                finding["reasons"].append(f"built from high-risk source columns {inherited}")
        elif base_risk.get(f) == "high" and finding["risk"] != "high":
            finding["risk"] = "high"
            finding["reasons"].append("flagged high leakage risk in data catalog")
        out.append(finding)
    return out


def evaluate_model(
    model, version: str, candidate_ref: str, count_test: bool = True, compare_to_reference: bool = True, store=None
) -> dict:
    s = get_settings()
    store = store or get_store("harness")
    if model.definition_version != version:
        raise DefinitionMismatchError(
            f"candidate trained under {model.definition_version} cannot be evaluated under {version}"
        )
    th, lk, fcfg = s.thresholds["gate"], s.thresholds["leakage"], s.thresholds["fairness"]

    dev = load_dev_frame(store, version, "harness.evaluate")
    train = dev[dev["split"] == "train"].reset_index(drop=True)
    val = dev[dev["split"] == "validation"].reset_index(drop=True)
    p_train, p_val = model.predict_pd(train), model.predict_pd(val)
    y_val = val["label"].to_numpy()

    m = metrics.summary(y_val, p_val)
    slices = _slice_aucs(val, p_val)
    segs = _segment_aucs(val, p_val)
    thin = val["thin_file"].astype(bool).to_numpy() if "thin_file" in val else np.zeros(len(val), bool)
    thin_auc = metrics.auc(y_val[thin], p_val[thin]) if thin.sum() >= 50 else float("nan")
    score_psi = metrics.psi(p_train, p_val)

    cat = catalog_lookup(store, version)
    leaks = feature_leakage(model, train, cat, lk)

    meta = read_split_meta(store, version)
    pop = window_population(store, meta["val_start"], meta["val_end"])
    pop_pd = model.predict_pd(pop)
    prot = fairness.protected_frame(store)
    classes = s.protected["protected_classes"]
    fair = fairness.adverse_impact(
        pd.DataFrame({"application_id": pop["application_id"], "pd": pop_pd}), prot, classes, fcfg["approval_rate"]
    )
    feats = apply_features(pop, [x for x in model.engineered if x.name not in pop])
    prox = fairness.proxy_summary(
        fairness.proxy_scores(feats[["application_id", *model.features]], prot, classes), fcfg["proxy_auc_flag"]
    )
    flagged_proxies = sorted(f for f, v in prox.items() if v["flag"])

    declined = pop_pd > fair["cutoff_pd"]
    rng = np.random.default_rng(0)
    idx = np.where(declined)[0]
    sample = np.zeros(len(pop), bool)
    sample[rng.choice(idx, size=min(2000, len(idx)), replace=False)] = True
    desc = dict(zip(cat["variable"], cat["description"], strict=False))
    codes = reason_codes.reason_codes(model, pop, sample, s.thresholds["reason_codes"]["top_n"], desc)
    prohibited_used = sorted(set(model.features) & prohibited_features())
    rq = reason_codes.reason_quality(
        codes, int(sample.sum()), s.thresholds["reason_codes"]["top_n"], set(flagged_proxies) | prohibited_features()
    )

    # ---- reference (same definition version only) ---------------------------------------------------
    reference = {"kind": "none", "auc": float("nan")}
    if compare_to_reference:
        champ = champion_for(version)
        if champ is not None:
            mv, cmodel = champ
            if cmodel.definition_version != version:  # defense in depth; champion_for already checks
                raise DefinitionMismatchError("reference champion has a different definition_version")
            reference = {"kind": "champion", "model_version": mv, "auc": metrics.auc(y_val, cmodel.predict_pd(val))}
        else:
            ref = reference_metrics(store, version)
            if ref:
                reference = {
                    "kind": "baseline",
                    "model_version": ref.get("baseline_model_version"),
                    "auc": float(ref["val_auc"]),
                }
    n_before = multiple_testing.n_tests(store, version)
    n_now = n_before + (1 if count_test else 0)
    margin = multiple_testing.required_margin(n_now, th)

    worst_slice = min(slices.values()) if slices else m["auc"]
    min_seg = min(segs.values()) if segs else m["auc"]
    checks = {
        "improves_on_reference": bool(reference["kind"] == "none" or m["auc"] >= reference["auc"] + margin),
        "calibration": bool(m["ece"] <= th["max_ece"]),
        "time_stability": bool(worst_slice >= m["auc"] - th["max_slice_auc_drop"]),
        "segment_floor": bool(min_seg >= th["min_segment_auc"]),
        "score_psi": bool(score_psi <= th["max_score_psi"]),
        "no_leakage": not any(x["risk"] == "high" for x in leaks),
        "no_prohibited_features": not prohibited_used,
        "no_proxy_features": not flagged_proxies,
        "adverse_impact": bool(fair["min_air"] >= fcfg["min_air"]),
        "reason_codes": bool(rq["coverage_any"] >= 0.99 and rq["flagged_feature_share"] == 0.0),
    }
    result = {
        "eval_id": f"ev-{uuid.uuid4().hex[:10]}",
        "candidate_ref": candidate_ref,
        "definition_version": version,
        "ts": datetime.now(UTC).isoformat(),
        "model": model.describe(),
        "validation": m,
        "lift": metrics.lift_by_decile(y_val, p_val).to_dict("records"),
        "calibration_table": metrics.calibration_table(y_val, p_val).to_dict("records"),
        "time_slices": slices,
        "segments": segs,
        "thin_file_auc": thin_auc,
        "score_psi_train_val": score_psi,
        "leakage": leaks,
        "fairness": fair,
        "proxies_flagged": flagged_proxies,
        "proxy_detail": {k: v for k, v in prox.items() if v["proxy_auc"] > 0.55},
        "prohibited_features_used": prohibited_used,
        "reason_code_quality": rq,
        "reason_code_sample": codes.head(40).to_dict("records"),
        "reference": reference,
        "n_tests": n_now,
        "required_margin": margin,
        "checks": checks,
        "passed_validation": all(checks.values()),
        "feature_importance": dict(list(model.feature_importance().items())[:25]),
    }
    if count_test:
        multiple_testing.record(store, version, candidate_ref)
    store.write_df(
        "ops",
        "evaluations",
        pd.DataFrame(
            [
                {
                    "eval_id": result["eval_id"],
                    "candidate_ref": candidate_ref,
                    "definition_version": version,
                    "ts": datetime.now(UTC),
                    "passed_validation": result["passed_validation"],
                    "val_auc": m["auc"],
                    "reference_auc": reference["auc"],
                    "required_margin": margin,
                    "n_tests": n_now,
                    "result_json": json.dumps(result, default=_json_default),
                }
            ]
        ),
        mode="append",
    )
    return result


def reference_metrics(store, version: str) -> dict | None:
    if not store.table_exists("ops", "harness_reference"):
        return None
    df = store.query(
        f"SELECT * FROM {store.fq('ops', 'harness_reference')} WHERE definition_version = '{version}' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    return None if df.empty else df.iloc[0].to_dict()


def latest_evaluation(store, candidate_ref: str) -> dict | None:
    if not store.table_exists("ops", "evaluations"):
        return None
    df = store.query(
        f"SELECT result_json FROM {store.fq('ops', 'evaluations')} WHERE candidate_ref = '{candidate_ref}' "
        "ORDER BY ts DESC LIMIT 1"
    )
    return None if df.empty else json.loads(df["result_json"].iloc[0])


def _json_default(o):
    if isinstance(o, np.integer | np.floating):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)
