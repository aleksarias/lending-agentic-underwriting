"""Plant a running improvement cycle in a LOCAL console lake, for building and checking the live-activity screen.

Writes an `ops.cycles` row with status "running", heartbeats for the agents that have started, and a few trace
entries (proposed, measured and system). Local DuckDB lakes only; never run against Databricks.

    uv run python scripts/console_plant_live_cycle.py --lake .local_lake/console_fe2          # plant (or refresh)
    uv run python scripts/console_plant_live_cycle.py --lake .local_lake/console_fe2 --remove # clean up
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
CYCLE = "cy-dev-live-0001"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", required=True, help="local lake directory (a copy of the console fixture)")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()
    os.environ["LAU_BACKEND"] = "local"
    os.environ["LAU_LOCAL_LAKE"] = str(Path(args.lake).resolve())

    import pandas as pd

    from lau.store import get_store

    st = get_store("admin")
    for table in ("cycles", "cycle_heartbeat", "agent_trace", "cycle_control"):
        if st.table_exists("ops", table):
            st.execute(f"DELETE FROM {st.fq('ops', table)} WHERE cycle_id = '{CYCLE}'")
    if args.remove:
        print(f"removed {CYCLE}")
        return
    active = st.query(f"SELECT definition_version FROM {st.fq('ops', 'active_definition')} ORDER BY activated_at DESC")
    version = str(active["definition_version"].iloc[0])
    now = datetime.now(UTC)
    start = now - timedelta(minutes=6)
    st.write_df(
        "ops",
        "cycles",
        pd.DataFrame(
            [
                {
                    "cycle_id": CYCLE,
                    "definition_version": version,
                    "reason": "monitoring_alert",
                    "started_at": start,
                    "status": "running",
                    "summary_json": "{}",
                }
            ]
        ),
        mode="append",
    )
    beats = [
        (start, "start", None, "running", 0, 0.0),
        (start + timedelta(seconds=5), "planner", "planner", "running", 0, 0.0),
        (start + timedelta(seconds=44), "planner", "planner", "done", 0, 0.12),
        (start + timedelta(seconds=46), "feature", "feature", "running", 0, 0.12),
        (start + timedelta(minutes=3), "feature", "feature", "done", 0, 0.24),
        (start + timedelta(minutes=3, seconds=2), "modeling", "modeling", "running", 1, 0.24),
        (now - timedelta(seconds=20), "modeling", "modeling", "running", 2, 0.31),
    ]
    st.write_df(
        "ops",
        "cycle_heartbeat",
        pd.DataFrame(
            [
                {"ts": t, "cycle_id": CYCLE, "step": s, "agent": a, "state": x, "experiments_used": e, "spent_usd": u}
                for t, s, a, x, e, u in beats
            ]
        ).astype({"experiments_used": "int32"}),
        mode="append",
    )

    def row(t, agent, action, inputs, outputs, state_changing, cost=0.0, status="ok"):
        return {
            "ts": t,
            "cycle_id": CYCLE,
            "definition_version": version,
            "agent": agent,
            "principal": "agent",
            "action": action,
            "state_changing": state_changing,
            "inputs": json.dumps(inputs),
            "outputs": json.dumps(outputs),
            "cost_usd": cost,
            "status": status,
        }

    trace = [
        row(start + timedelta(seconds=20), "planner", "get_status", {}, {"active_definition": version}, False),
        row(
            start + timedelta(seconds=40),
            "planner",
            "submit_plan",
            {"focus": "Recover lift lost to score drift (PSI 0.30) without using drifted bureau fields.", "goals": []},
            {"accepted": True},
            True,
        ),
        row(
            start + timedelta(seconds=44),
            "planner",
            "agent_run",
            {"prompt": "Plan this improvement cycle.", "model": "claude-opus-5-5"},
            {"subtype": "success", "turns": 3, "tool_calls": ["get_status", "submit_plan"]},
            False,
            0.12,
        ),
        row(start + timedelta(minutes=1), "feature", "catalog_summary", {"top": 25}, {"n_variables": 156}, False),
        row(
            start + timedelta(minutes=2),
            "feature",
            "propose_feature",
            {"name": "cf_balance_trend_6m", "expression": "cf_avg_balance_3m / nullif(cf_avg_balance_6m, 0)"},
            {"feature_id": "ft-dev-1"},
            True,
        ),
        row(
            start + timedelta(minutes=3),
            "feature",
            "agent_run",
            {"prompt": "Plan goals: ...", "model": "claude-sonnet-5-5"},
            {"subtype": "success", "turns": 9, "tool_calls": ["catalog_summary", "propose_feature"]},
            False,
            0.12,
        ),
        row(
            start + timedelta(minutes=4),
            "modeling",
            "train_candidate",
            {"model_type": "lightgbm", "features": ["bureau_score", "cf_balance_trend_6m"]},
            {"model_version": "13"},
            True,
        ),
        row(
            now - timedelta(seconds=30),
            "modeling",
            "evaluate_candidate",
            {"model_version": "13"},
            {"passed_validation": False, "val_auc": 0.7219},
            True,
        ),
    ]
    st.write_df("ops", "agent_trace", pd.DataFrame(trace), mode="append")
    print(f"planted running cycle {CYCLE} under definition {version} in {args.lake}")


if __name__ == "__main__":
    main()
