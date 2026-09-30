"""Improvement-cycle orchestrator (plain Python; the planner LLM only proposes a plan that Python validates).

Cycle:
  0. preflight: YAML definition == active definition (agents never apply definitions), monthly + cycle caps
  1. planner      -> plan (validated & capped)
  2. profiler     -> profile report + advisory flags            (optional per plan)
  3. feature      -> engineered features registered + screened
  4. modeling     -> candidates trained + harness-evaluated; one challenger proposed
  5. red team     -> verdict; if "fail" and rounds remain: modeling revises (max_critique_rounds)
  6. compliance   -> finding
  7. challenger alias set if validation passed and no fail/block  (NOT promoted; human runs `lau promote`)
  8. curator      -> LESSONS.md
  9. cycle report + trace flush + cost log
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime

import pandas as pd

from lau import cost
from lau.agents import lessons as lessons_mod
from lau.agents.runner import AgentRunError, CycleContext, run_agent
from lau.agents.tools import role_tools as rt
from lau.credentials import has_anthropic_key
from lau.definition.hashing import definition_version
from lau.definition.registry import active_version
from lau.definition.schema import load_definition
from lau.harness.evaluate import latest_evaluation
from lau.settings import CONFIG_DIR, get_settings
from lau.store import get_store
from lau.trace import TraceWriter


class CyclePreconditionError(RuntimeError):
    pass


def _status(ctx: CycleContext) -> dict:
    st = get_store("harness")
    ref = st.query(
        f"SELECT val_auc, val_ks, val_ece, baseline_model_version, required_margin_at_1 FROM "
        f"{st.fq('ops', 'harness_reference')} WHERE definition_version = '{ctx.version}'"
    )
    last = (
        st.query(
            f"SELECT cycle_id, status, summary_json FROM {st.fq('ops', 'cycles')} "
            f"WHERE definition_version = '{ctx.version}' ORDER BY started_at DESC LIMIT 1"
        )
        if st.table_exists("ops", "cycles")
        else pd.DataFrame()
    )
    from lau.harness.multiple_testing import n_tests

    return {
        "definition_version": ctx.version,
        "budgets": {
            "max_experiments": ctx.budgets["cycle"]["max_experiments"],
            "anthropic_usd_remaining": round(ctx.remaining_usd(), 2),
            "tests_already_run_on_validation": n_tests(st, ctx.version),
        },
        "reference_baseline": json.loads(ref.to_json(orient="records"))[0] if len(ref) else None,
        "catalog": rt.catalog_summary(ctx.version, 15),
        "registered_features": rt._list_feats(ctx)["features"][:30],
        "lessons": lessons_mod.lessons_for_prompt(ctx.version),
        "last_cycle": json.loads(last.to_json(orient="records"))[0] if len(last) else None,
    }


def preflight() -> str:
    if not has_anthropic_key():
        raise CyclePreconditionError("ANTHROPIC_API_KEY missing in .env")
    st = get_store("harness")
    active = active_version(st)
    yaml_v = definition_version(load_definition(CONFIG_DIR / "default_definition.yaml"))
    if active is None:
        raise CyclePreconditionError("no active definition; run `lau default-definition plan` then `apply`")
    if yaml_v != active:
        raise CyclePreconditionError(
            f"default_definition.yaml ({yaml_v}) differs from the active definition ({active}). A human must run "
            "`lau default-definition plan` and `apply` first; agents never change the definition."
        )
    return active


async def run_cycle(reason: str = "manual", log=print) -> dict:
    version = preflight()
    est = cost.estimate_stages(["improvement_cycle"], include_agents=True)
    cost.check_cycle_caps(est)
    cost.check_monthly_cap(est.total_usd)
    cycle_id = f"cy-{datetime.now(UTC):%Y%m%d%H%M}-{uuid.uuid4().hex[:4]}"
    ctx = CycleContext(cycle_id=cycle_id, version=version, trace=TraceWriter(cycle_id, version))
    st = get_store("harness")
    log(f"cycle {cycle_id} under definition {version} ({reason})\n{est.render()}")
    st.write_df(
        "ops",
        "cycles",
        pd.DataFrame(
            [
                {
                    "cycle_id": cycle_id,
                    "definition_version": version,
                    "reason": reason,
                    "started_at": datetime.now(UTC),
                    "status": "running",
                    "summary_json": "{}",
                }
            ]
        ),
        mode="append",
    )
    outcome: dict = {"cycle_id": cycle_id, "definition_version": version, "steps": []}
    status = "completed"
    try:
        await _run_steps(ctx, outcome, log)
    except AgentRunError as e:
        status = "failed_agent_api"
        outcome["stop_reason"] = str(e)
        log(f"cycle stopped: agent API error: {e}")
    except cost.BudgetExceededError as e:
        status = "stopped_budget"
        outcome["stop_reason"] = str(e)
        log(f"cycle stopped: {e}")
    except Exception as e:  # noqa: BLE001 - record and re-raise after writing the report
        status = "failed"
        outcome["stop_reason"] = f"{type(e).__name__}: {e}"
        log(f"cycle failed: {e}")
    finally:
        outcome.update(
            {
                "status": status,
                "anthropic_usd": round(ctx.spent_usd, 4),
                "per_agent": ctx.per_agent,
                "experiments_used": ctx.experiments_used,
                "features_proposed": ctx.features_proposed,
                "wall_clock_s": round(time.time() - ctx.started, 1),
            }
        )
        report_path = _write_cycle_report(ctx, outcome)
        outcome["report"] = str(report_path)
        ctx.trace.flush()
        cost.log_cost("anthropic", ctx.spent_usd, cycle_id=cycle_id, details="agent runs")
        dbu, usd = cost.metered_warehouse_usd()
        if usd:
            cost.log_cost("databricks_metered", usd, cycle_id=cycle_id, dbu=dbu)
        st.execute(
            f"UPDATE {st.fq('ops', 'cycles')} SET status = '{status}', "
            f"summary_json = '{json.dumps(_brief(outcome)).replace(chr(39), chr(39) * 2)}' "
            f"WHERE cycle_id = '{cycle_id}'"
        )
        if st.table_exists("ops", "cycle_queue"):
            st.execute(
                f"UPDATE {st.fq('ops', 'cycle_queue')} SET status = 'done' "
                f"WHERE definition_version = '{version}' AND status = 'queued'"
            )
    return outcome


def _brief(o: dict) -> dict:
    return {
        k: o.get(k)
        for k in (
            "status",
            "challenger",
            "challenger_passed_validation",
            "redteam_verdict",
            "compliance_verdict",
            "anthropic_usd",
            "experiments_used",
            "stop_reason",
        )
    }


async def _run_steps(ctx: CycleContext, outcome: dict, log) -> None:
    b = ctx.budgets["cycle"]

    # 1. plan
    r = await run_agent("planner", "Plan this improvement cycle.", rt.planner_tools(ctx, lambda: _status(ctx)), ctx)
    plan = ctx.state.get("plan") or {
        "goals": ["improve on baseline"],
        "feature_hypotheses": [],
        "model_types": ["logreg", "lightgbm"],
        "n_experiments": min(6, b["max_experiments"]),
        "run_profiler": True,
        "focus": "fallback plan (planner produced none)",
    }
    outcome["plan"] = plan
    outcome["steps"].append(_step(r))
    log(f"plan: {json.dumps(plan)[:400]}")

    # 2. profile
    if plan.get("run_profiler", True):
        r = await run_agent(
            "profiler", "Profile the data for the active definition and write your report.", rt.profiler_tools(ctx), ctx
        )
        outcome["steps"].append(_step(r))

    # 3. features
    hyp = "\n".join(f"- {h}" for h in plan.get("feature_hypotheses", [])) or "- (none given; use your judgement)"
    r = await run_agent(
        "feature",
        f"Plan goals: {plan['goals']}\nFeature hypotheses to test:\n{hyp}\n"
        f"Propose at most {b['max_features_proposed']} features.",
        rt.feature_tools(ctx),
        ctx,
    )
    outcome["steps"].append(_step(r))

    # 4-5. model + critique loop
    n_exp = min(int(plan["n_experiments"]), b["max_experiments"])
    task = (
        f"Plan goals: {plan['goals']}. Model types to try: {plan['model_types']}. You may run at most {n_exp} "
        f"harness evaluations this cycle. New engineered features this cycle: {ctx.state.get('features', [])}."
    )
    r = await run_agent("modeling", task, rt.modeling_tools(ctx), ctx)
    outcome["steps"].append(_step(r))
    rounds = 0
    verdict = None
    while ctx.state.get("proposed_challenger"):
        mv = ctx.state["proposed_challenger"]
        r = await run_agent("redteam", f"Red-team candidate model_version {mv}.", rt.redteam_tools(ctx), ctx)
        outcome["steps"].append(_step(r))
        verdict = _latest_verdict(ctx, "redteam", mv)
        if verdict != "fail" or rounds >= b["max_critique_rounds"]:
            break
        rounds += 1
        findings = _report_body(ctx, "redteam", mv)
        ctx.state.pop("proposed_challenger", None)
        r = await run_agent(
            "modeling",
            f"Your candidate {mv} FAILED red-team review (round {rounds}). Findings:\n"
            f"{findings[:6000]}\nRevise: train and evaluate a fixed candidate and propose it. "
            f"Remaining evaluation budget this cycle: {b['max_experiments'] - ctx.experiments_used}.",
            rt.modeling_tools(ctx),
            ctx,
        )
        outcome["steps"].append(_step(r))
        if not ctx.state.get("proposed_challenger"):
            break
    outcome["critique_rounds"] = rounds
    mv = ctx.state.get("proposed_challenger")
    outcome["challenger"] = mv
    outcome["redteam_verdict"] = verdict

    # 6. compliance
    if mv:
        r = await run_agent("compliance", f"Review candidate model_version {mv}.", rt.compliance_tools(ctx), ctx)
        outcome["steps"].append(_step(r))
        outcome["compliance_verdict"] = _latest_verdict(ctx, "compliance", mv)
        ev = latest_evaluation(get_store("harness"), f"candidate:{mv}")
        outcome["challenger_passed_validation"] = bool(ev and ev["passed_validation"])
        outcome["challenger_eval"] = rt._eval_summary(ev) if ev else None
        if outcome["challenger_passed_validation"] and verdict != "fail" and outcome["compliance_verdict"] != "block":
            _set_challenger_alias(ctx.version, mv)
            outcome["next_step"] = (
                f"Human review: `lau promote {mv}` runs the holdout gate, asks for your approval, then promotes."
            )
        else:
            outcome["next_step"] = "Challenger not eligible for promotion this cycle (see checks/verdicts)."

    # 8. curate
    r = await run_agent("curator", "Distil this cycle into lessons.", rt.curator_tools(ctx), ctx)
    outcome["steps"].append(_step(r))


def _step(r) -> dict:
    return {
        "role": r.role,
        "subtype": r.subtype,
        "turns": r.num_turns,
        "cost_usd": round(r.cost_usd, 4),
        "tool_calls": len(r.tool_calls),
        "duration_s": round(r.duration_s, 1),
    }


def _latest_verdict(ctx: CycleContext, kind: str, mv: str) -> str | None:
    reps = [x for x in ctx.state.get("reports", []) if x["kind"] == kind and x["candidate_ref"] == f"candidate:{mv}"]
    return reps[-1]["verdict"] if reps else None


def _report_body(ctx: CycleContext, kind: str, mv: str) -> str:
    st = get_store("agent")
    df = st.query(
        f"SELECT body FROM {st.fq('experiments', 'reports')} WHERE cycle_id = '{ctx.cycle_id}' "
        f"AND kind = '{kind}' AND candidate_ref = 'candidate:{mv}' ORDER BY created_at DESC LIMIT 1"
    )
    return "" if df.empty else str(df["body"].iloc[0])


def _set_challenger_alias(version: str, mv: str) -> None:
    from lau.modeling import registry_io

    with registry_io.mlflow_session("harness") as c:
        c.set_registered_model_alias(registry_io.candidate_model_name(), registry_io.challenger_alias(version), mv)


def _write_cycle_report(ctx: CycleContext, o: dict):
    s = get_settings()
    d = s.reports_dir / ctx.cycle_id
    d.mkdir(parents=True, exist_ok=True)
    ev = o.get("challenger_eval") or {}
    lines = [
        f"# Improvement cycle {ctx.cycle_id}",
        "",
        f"- Definition version: `{ctx.version}`",
        f"- Status: **{o.get('status')}**" + (f" — {o.get('stop_reason')}" if o.get("stop_reason") else ""),
        f"- Anthropic spend: ${o.get('anthropic_usd', 0):.2f} (cap ${ctx.budgets['cycle']['max_anthropic_usd']:.2f}); "
        f"experiments: {o.get('experiments_used')} (cap {ctx.budgets['cycle']['max_experiments']}); "
        f"wall clock {o.get('wall_clock_s')} s",
        "",
        "## Plan",
        "```json",
        json.dumps(o.get("plan", {}), indent=2),
        "```",
        "## Outcome",
        f"- Challenger: `{o.get('challenger')}`; passed validation checks: {o.get('challenger_passed_validation')}",
        f"- Red-team verdict: {o.get('redteam_verdict')} (critique rounds: {o.get('critique_rounds', 0)}); "
        f"compliance verdict: {o.get('compliance_verdict')}",
        f"- Next step: {o.get('next_step', '-')}",
    ]
    if ev:
        lines += [
            "",
            "### Challenger validation metrics (harness)",
            "```json",
            json.dumps(
                {k: ev.get(k) for k in ("validation", "reference", "required_margin", "n_tests", "checks")},
                indent=2,
                default=str,
            ),
            "```",
        ]
    lines += [
        "",
        "## Agent runs",
        "| role | result | turns | tool calls | cost $ | seconds |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {x['role']} | {x['subtype']} | {x['turns']} | {x['tool_calls']} | {x['cost_usd']:.3f} | {x['duration_s']} |"
        for x in o.get("steps", [])
    ]
    lines += [
        "",
        "## Artifacts",
        *[
            f"- {r['kind']} by {r['author']}: `{r['report_id']}` (verdict: {r.get('verdict') or '-'})"
            for r in ctx.state.get("reports", [])
        ],
        f"- Features proposed: {ctx.state.get('features', [])}",
        f"- Candidates trained: {ctx.state.get('candidates', [])}",
        "",
        "_Nothing in this cycle changed production. Promotion requires the holdout gate and a recorded "
        "human approval._",
    ]
    p = d / "cycle_report.md"
    p.write_text("\n".join(lines) + "\n")
    return p


async def run_single_agent(role: str) -> dict:
    """Run one specialist outside a full cycle (e.g. `lau profile`)."""
    version = preflight()
    cycle_id = f"{role}-{datetime.now(UTC):%Y%m%d%H%M}-{uuid.uuid4().hex[:4]}"
    ctx = CycleContext(cycle_id=cycle_id, version=version, trace=TraceWriter(cycle_id, version))
    tools = {"profiler": rt.profiler_tools}[role](ctx)
    try:
        r = await run_agent(role, "Profile the data for the active definition and write your report.", tools, ctx)
    finally:
        ctx.trace.flush()
        cost.log_cost("anthropic", ctx.spent_usd, cycle_id=cycle_id, details=role)
    return {"cycle_id": cycle_id, **_step(r), "reports": ctx.state.get("reports", []), "final_text": r.text[-2000:]}


def run_cycle_sync(reason: str = "manual", log=print) -> dict:
    return asyncio.run(run_cycle(reason, log))
