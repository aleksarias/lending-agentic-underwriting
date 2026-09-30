"""Ask: a read-only Claude agent that answers questions from the console's data.

Same isolation as the cycle specialists (lau.agents.runner): no built-in tools, only two in-process MCP tools,
dontAsk permissions, scrubbed environment, turn/budget/time caps. Its SQL runs as the read-only "ui" role, so it can
see exactly what the console can see and nothing else; row-level shadow scores are readable only in aggregate.
Every question is traced to ops.agent_trace and its cost logged against the monthly hard stop.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import sqlglot
from sqlglot import exp

from lau.governance.grants import UI_READABLE_OBJECTS
from lau.settings import get_settings

log = logging.getLogger(__name__)
ROLE = "ask"
UI_SCHEMAS = ("ops", "experiments", "feature_registry", "production")
AGGREGATE_ONLY_TABLES = {"shadow_scores"}
_LOCK = asyncio.Lock()  # one question at a time: spend stays predictable


class AskUnavailableError(RuntimeError):
    pass


def check_aggregate_only(sql: str) -> None:
    """Row-level tables may be queried only through aggregates (no individual application's score)."""
    for stmt in sqlglot.parse(sql, read="databricks"):
        if stmt is None:
            continue
        names = {t.name for t in stmt.find_all(exp.Table)}
        hit = names & AGGREGATE_ONLY_TABLES
        if hit and not any(True for _ in stmt.find_all(exp.AggFunc)):
            raise PermissionError(f"{', '.join(sorted(hit))} can only be queried with aggregates (count, avg, ...)")


def describe_ui_tables() -> dict:
    """Fully qualified names and columns of every table the ui role can read."""
    from lau.store import get_store

    st = get_store("ui")
    s = get_settings()
    tables: dict[str, list[str]] = {}
    for key in UI_SCHEMAS:
        try:
            if st.backend == "local":
                df = st.con.execute(  # type: ignore[attr-defined]
                    "SELECT table_name FROM information_schema.tables WHERE table_catalog = ? AND table_schema = ?",
                    [s.catalog, s.schema(key)],
                ).df()
                names = list(df["table_name"])
            else:
                names = [t.name for t in st.w.tables.list(catalog_name=s.catalog, schema_name=s.schema(key))]  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a schema the role cannot list is skipped
            names = []
        for n in sorted(names):
            tables[st.fq(key, n)] = []
    for key, objs in UI_READABLE_OBJECTS.items():
        for n in objs:
            tables[st.fq(key, n)] = []
    for fq in list(tables):
        try:
            tables[fq] = list(st.query(f"SELECT * FROM {fq} LIMIT 0").columns)
        except Exception:  # noqa: BLE001 - not visible to this role
            tables.pop(fq)
    return {"tables": tables}


def _tools(ctx, queries: list[dict]) -> list:
    from lau.agents.tools.common import S, frame_payload, obj_schema, readonly_sql, wrap

    def sql_query(a: dict) -> dict:
        sql = str(a["sql"])
        check_aggregate_only(sql)
        df = readonly_sql(sql, role="ui")
        queries.append({"sql": sql, "rows": int(len(df))})
        return frame_payload(df)

    return [
        wrap(
            ctx,
            ROLE,
            "describe_tables",
            "List the tables you can read and their columns.",
            obj_schema({}),
            lambda a: describe_ui_tables(),
        ),
        wrap(
            ctx,
            ROLE,
            "sql_query",
            "Run ONE read-only SELECT (Databricks SQL) and get at most 200 rows back.",
            obj_schema({"sql": S("a single SELECT or WITH query using fully qualified table names")}),
            sql_query,
        ),
    ]


async def answer(question: str, user: str) -> dict:
    from lau import cost
    from lau.agents.runner import CycleContext, run_agent
    from lau.console.services import definitions as defs
    from lau.credentials import has_anthropic_key
    from lau.trace import TraceWriter

    if not has_anthropic_key():
        raise AskUnavailableError("ANTHROPIC_API_KEY is not configured for this console.")
    caps = get_settings().budgets["agents"][ROLE]
    cost.check_monthly_cap(float(caps["max_budget_usd"]))
    version = defs.active_version() or ""
    ask_id = f"ask-{uuid.uuid4().hex[:10]}"
    ctx = CycleContext(cycle_id=ask_id, version=version, trace=TraceWriter(ask_id, version))
    ctx.trace.log(
        ROLE, "question", {"question": question[:2000], "user": user}, None, principal="ui", state_changing=False
    )
    queries: list[dict] = []
    async with _LOCK:
        result = await run_agent(ROLE, question, _tools(ctx, queries), ctx)
    try:
        ctx.trace.flush()
        cost.log_cost("anthropic", result.cost_usd, details=f"console ask {ask_id}")
    except Exception as e:  # noqa: BLE001 - the answer is still returned, but the gap in the audit trail is logged
        log.warning("ask %s: could not write the trace or cost row: %s: %s", ask_id, type(e).__name__, e)
    text = result.text.strip() or "No answer was produced."
    if result.is_error:
        text = f"The question could not be answered ({result.subtype}). {text}"
    return {
        "answer": text,
        "queries": queries,
        "cost_usd": round(result.cost_usd, 4),
        "model": str(get_settings().models["agents"][ROLE]),
    }
