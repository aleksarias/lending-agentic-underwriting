"""Per-role tool sets. Each agent only ever receives its own list (see agents/orchestrator.py)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from lau.agents import lessons as lessons_mod
from lau.agents.runner import CycleContext
from lau.agents.tools.common import A, I, N, S, catalog_summary, common_tools, obj_schema, wrap, write_report
from lau.data import feature_registry as freg
from lau.data.features import apply_features, load_dev_frame, registered_specs
from lau.harness import metrics
from lau.harness.evaluate import evaluate_model, latest_evaluation
from lau.modeling import registry_io
from lau.modeling.search_space import SEARCH_SPACE
from lau.modeling.train import train_model
from lau.settings import get_settings
from lau.store import get_store

_MODEL_CACHE: dict[str, object] = {}


def _load_candidate(mv: str):
    mv = str(mv)
    if mv not in _MODEL_CACHE:
        _MODEL_CACHE[mv] = registry_io.load_pd_model(registry_io.candidate_uri(mv), "harness")
    return _MODEL_CACHE[mv]


def _eval_summary(ev: dict) -> dict:
    keep = [
        "eval_id",
        "candidate_ref",
        "definition_version",
        "n_tests",
        "required_margin",
        "checks",
        "passed_validation",
        "reference",
        "thin_file_auc",
        "score_psi_train_val",
        "proxies_flagged",
        "prohibited_features_used",
        "time_slices",
        "segments",
    ]
    out = {k: ev.get(k) for k in keep}
    out["validation"] = {k: round(v, 4) if isinstance(v, float) else v for k, v in ev["validation"].items()}
    out["leakage_high"] = [x["column"] for x in ev["leakage"] if x["risk"] == "high"]
    out["fairness_min_air"] = ev["fairness"]["min_air"]
    out["top_features"] = dict(list(ev["feature_importance"].items())[:10])
    return out


# ---------------------------------------------------------------------------------------------------------
def profiler_tools(ctx: CycleContext) -> list:
    role = "profiler"

    def flag(a: dict) -> dict:
        row = {
            "cycle_id": ctx.cycle_id,
            "definition_version": ctx.version,
            "variable": a["variable"],
            "risk": a["risk"],
            "reason": a["reason"][:1000],
            "created_at": datetime.now(UTC),
        }
        get_store("agent").write_df("experiments", "profiler_flags", pd.DataFrame([row]), mode="append")
        return {"recorded": True, "note": "advisory only; the harness makes the binding leakage decision"}

    return [
        *common_tools(ctx, role),
        wrap(
            ctx,
            role,
            "catalog_summary",
            "Summary of the data catalog for the active definition.",
            obj_schema({"top": I("how many top variables by train AUC", minimum=5, maximum=60)}, []),
            lambda a: catalog_summary(ctx.version, int(a.get("top", 25))),
        ),
        wrap(
            ctx,
            role,
            "flag_variable",
            "Record an advisory data-quality/leakage/proxy flag for a variable.",
            obj_schema(
                {
                    "variable": S("variable name"),
                    "risk": S("risk level", enum=["high", "medium", "low"]),
                    "reason": S("evidence"),
                }
            ),
            flag,
            state_changing=True,
        ),
        wrap(
            ctx,
            role,
            "write_report",
            "Save your profiling report (markdown).",
            obj_schema({"title": S("title"), "body": S("markdown body")}),
            lambda a: write_report(ctx, role, "profile", a["title"], a["body"]),
            state_changing=True,
        ),
    ]


# ---------------------------------------------------------------------------------------------------------
def feature_tools(ctx: CycleContext) -> list:
    role = "feature"

    def list_features(a: dict) -> dict:
        st = get_store("agent")
        if not st.table_exists("feature_registry", "features"):
            return {"features": []}
        f = st.query(
            f"SELECT name, expression, status, rationale, created_under_definition "
            f"FROM {st.fq('feature_registry', 'features')}"
        )
        perf = (
            st.query(
                f"SELECT * FROM {st.fq('feature_registry', 'feature_performance')} "
                f"WHERE definition_version = '{ctx.version}'"
            )
            if st.table_exists("feature_registry", "feature_performance")
            else pd.DataFrame(columns=["name"])
        )
        m = f.merge(perf, on="name", how="left")
        return {"features": json.loads(m.to_json(orient="records"))}

    def propose(a: dict) -> dict:
        cap = ctx.budgets["cycle"]["max_features_proposed"]
        if ctx.features_proposed >= cap:
            raise RuntimeError(f"feature proposal cap reached ({cap}) for this cycle")
        st = get_store("agent")
        cols = st.query(f"SELECT * FROM {st.fq('curated', 'applications_dev')} LIMIT 0").columns.tolist()
        row = freg.register_feature(
            st, a["name"], a["expression"], a["rationale"], a["hypothesis"], role, ctx.cycle_id, cols, ctx.version
        )
        ctx.features_proposed += 1
        train = load_dev_frame(st, ctx.version, "agent.feature.screen", splits=("train",))
        cat = st.query(
            f"SELECT variable, leakage_risk, proxy_risk FROM {st.fq('curated', 'data_catalog')} "
            f"WHERE definition_version = '{ctx.version}'"
        )
        spec = registered_specs(st, [a["name"]])
        perf = freg.evaluate_features(st, spec, train, cat, get_settings().thresholds["leakage"], ctx.version)
        st.write_df("feature_registry", "feature_performance", perf, mode="append")
        ctx.state.setdefault("features", []).append(a["name"])
        return {
            "registered": row["name"],
            "source_columns": json.loads(row["source_columns"]),
            "train_screen": json.loads(perf.to_json(orient="records"))[0],
        }

    return [
        *common_tools(ctx, role),
        wrap(
            ctx,
            role,
            "catalog_summary",
            "Summary of the data catalog for the active definition.",
            obj_schema({"top": I("top N by train AUC", minimum=5, maximum=60)}, []),
            lambda a: catalog_summary(ctx.version, int(a.get("top", 25))),
        ),
        wrap(
            ctx,
            role,
            "list_features",
            "List registered engineered features and their current-version metrics.",
            obj_schema({}),
            list_features,
        ),
        wrap(
            ctx,
            role,
            "propose_feature",
            "Register an engineered feature as a scalar SQL expression over applications_dev columns "
            "(e.g. 'loan_amount / nullif(annual_income, 0)'). It is validated, sandboxed, registered with lineage "
            "and screened on TRAIN labels only.",
            obj_schema(
                {
                    "name": S("snake_case name, 3-41 chars"),
                    "expression": S("scalar SQL expression"),
                    "rationale": S("why this could predict default"),
                    "hypothesis": S("testable hypothesis, e.g. 'higher X -> higher PD'"),
                }
            ),
            propose,
            state_changing=True,
        ),
        wrap(
            ctx,
            role,
            "write_report",
            "Save your feature-research report (markdown).",
            obj_schema({"title": S("title"), "body": S("markdown body")}),
            lambda a: write_report(ctx, role, "features", a["title"], a["body"]),
            state_changing=True,
        ),
    ]


# ---------------------------------------------------------------------------------------------------------
def modeling_tools(ctx: CycleContext) -> list:
    role = "modeling"

    def train(a: dict) -> dict:
        st = get_store("agent")
        model, df, m = train_model(
            st,
            ctx.version,
            a["model_type"],
            a.get("params") or {},
            a["features"],
            a.get("engineered_features") or [],
            consumer="agent.modeling.train",
        )
        _, mv = registry_io.log_candidate(
            model,
            m,
            {"author": role, "cycle_id": ctx.cycle_id, "lau_role": "challenger"},
            df,
            role="harness",  # agent trains (agent data grants); harness records the submission
            run_name=a.get("run_name") or f"{a['model_type']}_{ctx.cycle_id}",
        )
        ctx.state.setdefault("candidates", []).append(mv)
        return {
            "model_version": mv,
            "train_metrics": {k: round(v, 4) for k, v in m.items() if "auc" in k or "ece" in k},
            "n_features": len(model.features),
        }

    def evaluate(a: dict) -> dict:
        cap = ctx.budgets["cycle"]["max_experiments"]
        if ctx.experiments_used >= cap:
            raise RuntimeError(f"experiment cap reached ({cap}) for this cycle")
        mv = str(a["model_version"])
        model = _load_candidate(mv)
        ctx.experiments_used += 1
        ev = evaluate_model(model, ctx.version, f"candidate:{mv}", count_test=True)
        return _eval_summary(ev)

    def propose(a: dict) -> dict:
        mv = str(a["model_version"])
        ev = latest_evaluation(get_store("harness"), f"candidate:{mv}")
        if ev is None:
            raise RuntimeError("evaluate the candidate first")
        ctx.state["proposed_challenger"] = mv
        ctx.state["proposal_rationale"] = a["rationale"]
        return {
            "proposed": mv,
            "passed_validation": ev["passed_validation"],
            "note": "red-team and compliance review follow; promotion needs the holdout gate + human approval",
        }

    return [
        wrap(
            ctx,
            role,
            "catalog_summary",
            "Summary of the data catalog for the active definition.",
            obj_schema({"top": I("top N by train AUC", minimum=5, maximum=60)}, []),
            lambda a: catalog_summary(ctx.version, int(a.get("top", 40))),
        ),
        wrap(
            ctx,
            role,
            "list_features",
            "Registered engineered features with current-version screening metrics.",
            obj_schema({}),
            lambda a: _list_feats(ctx),
        ),
        wrap(
            ctx,
            role,
            "get_search_space",
            "Allowed model types and hyper-parameter ranges.",
            obj_schema({}),
            lambda a: SEARCH_SPACE,
        ),
        wrap(
            ctx,
            role,
            "train_candidate",
            "Train a challenger from the fixed template on the TRAIN split and register it. Returns model_version.",
            obj_schema(
                {
                    "model_type": S("model type", enum=list(SEARCH_SPACE)),
                    "params": {"type": "object", "description": "hyper-parameters within the search space"},
                    "features": A("base feature names (from the catalog)"),
                    "engineered_features": A("registered engineered feature names"),
                    "run_name": S("short run name"),
                },
                ["model_type", "features"],
            ),
            train,
            state_changing=True,
        ),
        wrap(
            ctx,
            role,
            "evaluate_candidate",
            "Ask the deterministic harness to evaluate a candidate on VALIDATION. Counts as one experiment and "
            "raises the required improvement margin for everyone. Returns checks and metrics.",
            obj_schema({"model_version": S("candidate model version")}),
            evaluate,
            state_changing=True,
        ),
        wrap(
            ctx,
            role,
            "propose_challenger",
            "Nominate ONE evaluated candidate for red-team/compliance review.",
            obj_schema({"model_version": S("candidate model version"), "rationale": S("why this one")}),
            propose,
            state_changing=True,
        ),
        wrap(
            ctx,
            role,
            "write_report",
            "Save your modeling report (markdown).",
            obj_schema({"title": S("title"), "body": S("markdown body")}),
            lambda a: write_report(ctx, role, "modeling", a["title"], a["body"]),
            state_changing=True,
        ),
    ]


def _list_feats(ctx: CycleContext) -> dict:
    st = get_store("agent")
    if not st.table_exists("feature_registry", "features"):
        return {"features": []}
    f = st.query(
        f"SELECT name, expression, status FROM {st.fq('feature_registry', 'features')} WHERE status <> 'rejected'"
    )
    if st.table_exists("feature_registry", "feature_performance"):
        p = st.query(
            f"SELECT name, univariate_auc_train, leakage_risk, proxy_risk FROM "
            f"{st.fq('feature_registry', 'feature_performance')} WHERE definition_version = '{ctx.version}'"
        )
        f = f.merge(p.drop_duplicates("name", keep="last"), on="name", how="left")
    return {"features": json.loads(f.to_json(orient="records"))}


# ---------------------------------------------------------------------------------------------------------
def _val_frame(version: str) -> pd.DataFrame:
    dev = load_dev_frame(get_store("harness"), version, "agent.redteam.probe")
    return dev[dev["split"] == "validation"].reset_index(drop=True)


def redteam_tools(ctx: CycleContext) -> list:
    role = "redteam"

    def get_eval(a: dict) -> dict:
        ev = latest_evaluation(get_store("harness"), f"candidate:{a['model_version']}")
        if ev is None:
            raise RuntimeError("no evaluation for that candidate")
        return {
            **_eval_summary(ev),
            "lift": ev["lift"],
            "calibration_table": ev["calibration_table"],
            "leakage": ev["leakage"],
        }

    def probe_segment(a: dict) -> dict:
        model = _load_candidate(a["model_version"])
        val = _val_frame(ctx.version)
        col = a["column"]
        if col not in val.columns or col in ("label",):
            raise ValueError("unknown or disallowed column")
        mask = val[col].astype(str) == str(a["value"])
        y, p = val.loc[mask, "label"].to_numpy(), model.predict_pd(val[mask])
        if mask.sum() < 50:
            return {"n": int(mask.sum()), "note": "segment too small (<50) for reliable metrics"}
        out = metrics.summary(y, p)
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in out.items()}

    def probe_perturbation(a: dict) -> dict:
        model = _load_candidate(a["model_version"])
        val = _val_frame(ctx.version)
        f = a["feature"]
        if f not in model.features:
            raise ValueError("feature not used by model")
        base = model.predict_pd(val)
        x = pd.to_numeric(val[f], errors="coerce")
        if x.notna().sum() == 0:
            raise ValueError("feature is not numeric")
        shifted = val.copy()
        shifted[f] = x + float(a["shift_sd"]) * x.std()
        p2 = model.predict_pd(shifted)
        rank_corr = pd.Series(base).rank().corr(pd.Series(p2).rank())
        return {
            "mean_abs_pd_change": float(np.mean(np.abs(p2 - base))),
            "mean_pd_before": float(base.mean()),
            "mean_pd_after": float(p2.mean()),
            "rank_correlation": float(rank_corr),
        }

    def probe_adverse_selection(a: dict) -> dict:
        model = _load_candidate(a["model_version"])
        val = _val_frame(ctx.version)
        ref = get_store("harness").query(
            f"SELECT baseline_model_version FROM {get_store('harness').fq('ops', 'harness_reference')} "
            f"WHERE definition_version = '{ctx.version}'"
        )
        refm = _load_candidate(str(ref["baseline_model_version"].iloc[0]))
        rate = get_settings().thresholds["fairness"]["approval_rate"]
        pc, pr = model.predict_pd(val), refm.predict_pd(val)
        ac, ar = pc <= np.quantile(pc, rate), pr <= np.quantile(pr, rate)
        y = val["label"].to_numpy()
        swap_in, swap_out = ac & ~ar, ~ac & ar
        return {
            "approval_rate": rate,
            "swap_in_n": int(swap_in.sum()),
            "swap_out_n": int(swap_out.sum()),
            "swap_in_default_rate": float(y[swap_in].mean()) if swap_in.any() else None,
            "swap_out_default_rate": float(y[swap_out].mean()) if swap_out.any() else None,
            "approved_default_rate_candidate": float(y[ac].mean()),
            "approved_default_rate_reference": float(y[ar].mean()),
            "caveat": "measured on previously-approved loans only (selection bias; see docs/reject-inference.md)",
        }

    def report(a: dict) -> dict:
        return write_report(
            ctx, role, "redteam", a["title"], a["body"], f"candidate:{a['model_version']}", a["verdict"]
        )

    return [
        wrap(
            ctx,
            role,
            "get_evaluation",
            "Full harness evaluation of a candidate (validation).",
            obj_schema({"model_version": S("candidate model version")}),
            get_eval,
        ),
        wrap(
            ctx,
            role,
            "probe_segment",
            "Validation metrics for one segment (column == value).",
            obj_schema(
                {
                    "model_version": S("candidate"),
                    "column": S("column in applications"),
                    "value": S("value to match (as string)"),
                }
            ),
            probe_segment,
        ),
        wrap(
            ctx,
            role,
            "probe_perturbation",
            "Shift a numeric input by k std-devs; report PD change and rank stability.",
            obj_schema(
                {
                    "model_version": S("candidate"),
                    "feature": S("model feature"),
                    "shift_sd": N("shift in standard deviations", minimum=-3, maximum=3),
                }
            ),
            probe_perturbation,
        ),
        wrap(
            ctx,
            role,
            "probe_adverse_selection",
            "Compare swap-in/swap-out default rates vs the baseline at the policy approval rate.",
            obj_schema({"model_version": S("candidate")}),
            probe_adverse_selection,
        ),
        wrap(
            ctx,
            role,
            "write_report",
            "Save your red-team report with a verdict.",
            obj_schema(
                {
                    "model_version": S("candidate"),
                    "title": S("title"),
                    "body": S("markdown"),
                    "verdict": S("verdict", enum=["pass", "concern", "fail"]),
                }
            ),
            report,
            state_changing=True,
        ),
    ]


# ---------------------------------------------------------------------------------------------------------
def compliance_tools(ctx: CycleContext) -> list:
    role = "compliance"

    def fairness_report(a: dict) -> dict:
        ev = latest_evaluation(get_store("harness"), f"candidate:{a['model_version']}")
        if ev is None:
            raise RuntimeError("no evaluation for that candidate")
        return {
            "fairness": ev["fairness"],
            "proxies_flagged": ev["proxies_flagged"],
            "proxy_detail": ev["proxy_detail"],
            "prohibited_features_used": ev["prohibited_features_used"],
            "approval_rate_assumed": get_settings().thresholds["fairness"]["approval_rate"],
            "min_air_threshold": get_settings().thresholds["fairness"]["min_air"],
        }

    def reason_report(a: dict) -> dict:
        ev = latest_evaluation(get_store("harness"), f"candidate:{a['model_version']}")
        if ev is None:
            raise RuntimeError("no evaluation for that candidate")
        return {"quality": ev["reason_code_quality"], "sample": ev["reason_code_sample"][: int(a.get("n", 20))]}

    def lineage(a: dict) -> dict:
        model = _load_candidate(a["model_version"])
        st = get_store("harness")
        lin = st.query(f"SELECT * FROM {st.fq('curated', 'field_lineage')}")
        lin = lin[lin["column_name"].isin(model.features)]
        eng = [
            {"name": s.name, "expression": s.expression, "sources": list(s.source_columns)} for s in model.engineered
        ]
        return {"base_lineage": json.loads(lin.to_json(orient="records")), "engineered": eng}

    def report(a: dict) -> dict:
        return write_report(
            ctx, role, "compliance", a["title"], a["body"], f"candidate:{a['model_version']}", a["verdict"]
        )

    return [
        wrap(
            ctx,
            role,
            "get_fairness_report",
            "Adverse impact ratios, proxy detection, prohibited-feature use.",
            obj_schema({"model_version": S("candidate")}),
            fairness_report,
        ),
        wrap(
            ctx,
            role,
            "get_reason_codes",
            "Adverse-action reason-code quality metrics and a sample.",
            obj_schema(
                {"model_version": S("candidate"), "n": I("sample size", minimum=1, maximum=40)}, ["model_version"]
            ),
            reason_report,
        ),
        wrap(
            ctx,
            role,
            "get_feature_lineage",
            "Lineage for every model input (source system, availability).",
            obj_schema({"model_version": S("candidate")}),
            lineage,
        ),
        wrap(
            ctx,
            role,
            "write_finding",
            "Save your compliance finding with a verdict.",
            obj_schema(
                {
                    "model_version": S("candidate"),
                    "title": S("title"),
                    "body": S("markdown"),
                    "verdict": S("verdict", enum=["pass", "concern", "block"]),
                }
            ),
            report,
            state_changing=True,
        ),
    ]


# ---------------------------------------------------------------------------------------------------------
def curator_tools(ctx: CycleContext) -> list:
    role = "curator"

    def artifacts(a: dict) -> dict:
        st = get_store("agent")
        rep = st.query(
            f"SELECT author, kind, title, verdict, candidate_ref, body FROM "
            f"{st.fq('experiments', 'reports')} WHERE cycle_id = '{ctx.cycle_id}'"
        )
        rep["body"] = rep["body"].str.slice(0, 3000)
        evs = [
            _eval_summary(latest_evaluation(get_store("harness"), f"candidate:{mv}"))
            for mv in ctx.state.get("candidates", [])
            if latest_evaluation(get_store("harness"), f"candidate:{mv}")
        ]
        return {
            "reports": json.loads(rep.to_json(orient="records")),
            "evaluations": evs,
            "features_proposed": ctx.state.get("features", []),
        }

    def add(a: dict) -> dict:
        entries = a["entries"][:8]
        new = lessons_mod.add_lessons(entries, ctx.version)
        return {"added": [le.line() for le in new]}

    def unverified(a: dict) -> dict:
        pending = f"unverified-under-{ctx.version[:8]}"
        return {"lessons": [le.line() for le in lessons_mod.read_lessons() if le.status == pending][:40]}

    def reverify(a: dict) -> dict:
        changed = lessons_mod.set_statuses(a["updates"][:20], ctx.version)
        return {"changed": changed}

    return [
        wrap(
            ctx,
            role,
            "read_cycle_artifacts",
            "Reports and evaluation summaries from this cycle.",
            obj_schema({}),
            artifacts,
        ),
        wrap(
            ctx,
            role,
            "read_lessons",
            "Current LESSONS.md entries relevant to this definition.",
            obj_schema({}),
            lambda a: lessons_mod.lessons_for_prompt(ctx.version),
        ),
        wrap(
            ctx,
            role,
            "list_unverified_lessons",
            "Lessons carried over from an earlier definition of default that still need re-checking under this one.",
            obj_schema({}),
            unverified,
        ),
        wrap(
            ctx,
            role,
            "reverify_lessons",
            "Mark carried-over lessons as active (this cycle's evidence supports them under the current "
            "definition) or retired (it contradicts them). Only lessons flagged unverified can change; give the "
            "evidence in reason.",
            obj_schema(
                {
                    "updates": A(
                        "decisions",
                        {
                            "type": "object",
                            "properties": {
                                "id": S("lesson id, e.g. L-3f2ab6"),
                                "status": S("active or retired", enum=["active", "retired"]),
                                "reason": S("the evidence from this cycle"),
                            },
                            "required": ["id", "status", "reason"],
                        },
                        maxItems=20,
                    )
                }
            ),
            reverify,
            state_changing=True,
        ),
        wrap(
            ctx,
            role,
            "add_lessons",
            "Append up to 8 concise, evidence-backed lessons.",
            obj_schema(
                {
                    "entries": A(
                        "lessons",
                        {
                            "type": "object",
                            "properties": {
                                "text": S("one-sentence lesson with evidence"),
                                "definition_independent": {
                                    "type": "boolean",
                                    "description": "true only if it holds under any default definition "
                                    "(e.g. a leakage pattern)",
                                },
                            },
                            "required": ["text", "definition_independent"],
                        },
                        maxItems=8,
                    )
                }
            ),
            add,
            state_changing=True,
        ),
    ]


# ---------------------------------------------------------------------------------------------------------
def planner_tools(ctx: CycleContext, status_fn) -> list:
    role = "planner"

    def submit(a: dict) -> dict:
        cap = ctx.budgets["cycle"]["max_experiments"]
        plan = {
            "goals": a["goals"][:5],
            "feature_hypotheses": a.get("feature_hypotheses", [])[:10],
            "model_types": [m for m in a.get("model_types", ["lightgbm", "logreg"]) if m in SEARCH_SPACE] or ["logreg"],
            "n_experiments": max(1, min(int(a.get("n_experiments", cap)), cap)),
            "run_profiler": bool(a.get("run_profiler", True)),
            "focus": a.get("focus", "")[:1000],
        }
        ctx.state["plan"] = plan
        return {"accepted_plan": plan}

    return [
        wrap(
            ctx,
            role,
            "get_status",
            "Current state: definition, budgets, catalog highlights, features, lessons, last cycle outcome.",
            obj_schema({}),
            lambda a: status_fn(),
        ),
        wrap(
            ctx,
            role,
            "submit_plan",
            "Submit the cycle plan (validated and capped by the orchestrator).",
            obj_schema(
                {
                    "goals": A("up to 5 goals"),
                    "feature_hypotheses": A("hypotheses for the feature agent"),
                    "model_types": A("model types to try", {"type": "string", "enum": list(SEARCH_SPACE)}),
                    "n_experiments": I("experiments to spend", minimum=1, maximum=50),
                    "run_profiler": {"type": "boolean", "description": "run the data profiler first"},
                    "focus": S("focus for this cycle"),
                },
                ["goals", "model_types", "n_experiments"],
            ),
            submit,
            state_changing=True,
        ),
    ]


__all__ = [
    "profiler_tools",
    "feature_tools",
    "modeling_tools",
    "redteam_tools",
    "compliance_tools",
    "curator_tools",
    "planner_tools",
    "apply_features",
]
