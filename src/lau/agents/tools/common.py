"""Shared tool plumbing: wrapping, tracing, read-only SQL, reports."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import sqlglot
from sqlglot import exp

from lau.agents.runner import CycleContext, tool_error, tool_text
from lau.masking import get_masker
from lau.settings import get_settings
from lau.store import AccessDeniedError, get_store

MAX_SQL_ROWS = 200


def wrap(
    ctx: CycleContext,
    role: str,
    name: str,
    desc: str,
    schema: dict,
    fn: Callable[[dict], Any],
    state_changing: bool = False,
):
    """Create an SDK tool whose handler runs `fn` off the event loop, traced, masked and redacted."""
    from claude_agent_sdk import tool

    @tool(name, desc, schema)
    async def handler(args: dict) -> dict:
        try:
            result = await asyncio.to_thread(fn, args)
            ctx.trace.log(role, name, args, result, state_changing=state_changing)
            return tool_text(result)
        except Exception as e:  # noqa: BLE001 - tool errors are returned to the agent, and traced
            ctx.trace.log(role, name, args, {"error": str(e)}, state_changing=state_changing, status="error")
            return tool_error(f"{type(e).__name__}: {e}")

    return handler


def obj_schema(props: dict[str, dict], required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props)}


def S(desc: str, **kw) -> dict:
    return {"type": "string", "description": desc, **kw}


def N(desc: str, **kw) -> dict:
    return {"type": "number", "description": desc, **kw}


def I(desc: str, **kw) -> dict:  # noqa: E743
    return {"type": "integer", "description": desc, **kw}


def A(desc: str, items: dict | None = None, **kw) -> dict:
    return {"type": "array", "description": desc, "items": items or {"type": "string"}, **kw}


# ---- read-only SQL ------------------------------------------------------------------------------------------
def readonly_sql(sql: str, role: str = "agent") -> pd.DataFrame:
    """Single SELECT only, schema allow-list via the role Store ACL (and UC grants on Databricks), row-capped."""
    stmts = [s for s in sqlglot.parse(sql, read="databricks") if s is not None]
    if len(stmts) != 1 or not isinstance(stmts[0], exp.Query):
        raise AccessDeniedError("only a single SELECT/WITH query is allowed")
    q = stmts[0]
    if any(
        isinstance(n, exp.Insert | exp.Create | exp.Delete | exp.Update | exp.Merge | exp.Drop | exp.Command)
        for n in q.walk()
    ):
        raise AccessDeniedError("write statements are not allowed")
    if isinstance(q, exp.Select):
        lim = q.args.get("limit")
        if lim is None or int(lim.expression.name or MAX_SQL_ROWS) > MAX_SQL_ROWS:
            q = q.limit(MAX_SQL_ROWS)
    else:
        q = exp.select("*").from_(q.subquery("q")).limit(MAX_SQL_ROWS)
    st = get_store(role)
    dialect = "duckdb" if st.backend == "local" else "databricks"
    df = st.query(q.sql(dialect=dialect))
    return get_masker().mask_frame(df)


def frame_payload(df: pd.DataFrame, max_rows: int = MAX_SQL_ROWS) -> dict:
    return {
        "n_rows": int(len(df)),
        "columns": list(df.columns),
        "rows": json.loads(df.head(max_rows).to_json(orient="records", date_format="iso")),
    }


def describe_agent_tables() -> dict:
    s = get_settings()
    st = get_store("agent")
    out = {}
    for key, table in [
        ("curated", "applications_dev"),
        ("curated", "data_catalog"),
        ("labels", "labels_active"),
        ("feature_registry", "features"),
        ("feature_registry", "feature_performance"),
        ("experiments", "reports"),
    ]:
        if st.table_exists(key, table):
            cols = st.query(f"SELECT * FROM {s.fq(key, table)} LIMIT 0").columns.tolist()
            out[s.fq(key, table)] = cols if len(cols) < 40 else cols[:40] + [f"... (+{len(cols) - 40} more)"]
    return {
        "readable_tables": out,
        "notes": [
            "labels_active holds TRAIN labels of the active definition only",
            "validation/holdout labels are never visible to agents; use evaluation tools",
            "SELECT only; results capped at 200 rows",
        ],
    }


def catalog_summary(version: str, top: int = 25) -> dict:
    st = get_store("agent")
    cat = st.query(
        f"SELECT variable, dtype, missing_rate, cardinality, univariate_auc_train, "
        f"drift_psi_early_train_vs_val, leakage_risk, leakage_reasons, proxy_risk, proxy_class, "
        f"availability, description FROM {st.fq('curated', 'data_catalog')} "
        f"WHERE definition_version = '{version}'"
    )
    cat = cat.sort_values("univariate_auc_train", ascending=False)
    return {
        "n_variables": int(len(cat)),
        "top_by_train_auc": json.loads(cat.head(top).to_json(orient="records")),
        "leakage_high": cat[cat["leakage_risk"] == "high"]["variable"].tolist(),
        "leakage_medium": cat[cat["leakage_risk"] == "medium"]["variable"].tolist(),
        "proxy_high": cat[cat["proxy_risk"] == "high"]["variable"].tolist(),
        "most_drifting": json.loads(
            cat.sort_values("drift_psi_early_train_vs_val", ascending=False)
            .head(10)[["variable", "drift_psi_early_train_vs_val"]]
            .to_json(orient="records")
        ),
    }


def write_report(
    ctx: CycleContext,
    author_role: str,
    kind: str,
    title: str,
    body: str,
    candidate_ref: str | None = None,
    verdict: str | None = None,
) -> dict:
    """Reports are the artifacts agents communicate through. author_role is set by code, never by the model."""
    s = get_settings()
    report_id = f"rp-{uuid.uuid4().hex[:10]}"
    row = {
        "report_id": report_id,
        "cycle_id": ctx.cycle_id,
        "definition_version": ctx.version,
        "author": author_role,
        "kind": kind,
        "title": title[:200],
        "body": body[:30000],
        "candidate_ref": candidate_ref or "",
        "verdict": verdict or "",
        "created_at": datetime.now(UTC),
    }
    get_store("agent").write_df("experiments", "reports", pd.DataFrame([row]), mode="append")
    d = s.reports_dir / ctx.cycle_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{kind}_{report_id}.md").write_text(
        f"# {title}\n\n_author: {author_role} | definition: {ctx.version} | "
        f"candidate: {candidate_ref or '-'} | verdict: {verdict or '-'}_\n\n" + body
    )
    ctx.state.setdefault("reports", []).append(
        {
            "report_id": report_id,
            "kind": kind,
            "author": author_role,
            "candidate_ref": candidate_ref,
            "verdict": verdict,
        }
    )
    return {"report_id": report_id, "saved": True}


def common_tools(ctx: CycleContext, role: str) -> list:
    return [
        wrap(
            ctx,
            role,
            "sql_query",
            "Run ONE read-only SELECT on tables you can read (see describe_tables). Use fully-qualified names. "
            "Max 200 rows returned.",
            obj_schema({"sql": S("A single SELECT statement")}),
            lambda a: frame_payload(readonly_sql(a["sql"])),
        ),
        wrap(
            ctx,
            role,
            "describe_tables",
            "List tables you can read and their columns.",
            obj_schema({}),
            lambda a: describe_agent_tables(),
        ),
    ]
