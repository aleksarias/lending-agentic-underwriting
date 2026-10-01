"""Shared helpers for console routers: safe table reads, JSON conversion, small TTL cache, unavailable payloads.

Every router reads through `read_table` / `query` with the console's read-only "ui" Store, so the console can only
ever see what the ui grants allow (metadata and aggregates; never raw applicant rows, all-version labels or holdout).
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import math
import re
import threading
import time
from collections.abc import Callable, Iterable
from datetime import date, datetime
from functools import wraps
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from lau.store import Store

_CACHE: dict[tuple, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()

# Time travel: evidence views computed as of a past instant. Set for one request with `evidence_as_of`; every
# latest-run lookup honours it, and cached results are keyed by it so views at different dates never mix.
AS_OF: contextvars.ContextVar[pd.Timestamp | None] = contextvars.ContextVar("lau_console_as_of", default=None)
AS_OF_PARAM = Query(None, alias="as_of", description="show evidence as computed at this date (YYYY-MM-DD) or instant")


def parse_as_of(value: str | None) -> pd.Timestamp | None:
    """'2026-09-30' means the end of that day (UTC); an ISO instant is used as given."""
    if not value:
        return None
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    if len(value) == 10:
        ts = ts + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return ts


@contextlib.contextmanager
def evidence_as_of(value: str | None):
    token = AS_OF.set(parse_as_of(value))
    try:
        yield AS_OF.get()
    finally:
        AS_OF.reset(token)


def as_of_sql(column: str = "computed_at") -> str:
    """A WHERE fragment limiting evidence rows to the time-travel instant ('' without one)."""
    ts = AS_OF.get()
    return "" if ts is None else f" WHERE {column} <= TIMESTAMP '{ts.isoformat(sep=' ')}'"


def ttl_cache(seconds: float = 30.0) -> Callable:
    """Cache a function's result for `seconds`, keyed by its arguments (hashable) and the time-travel instant."""

    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__module__, fn.__qualname__, args, tuple(sorted(kwargs.items())), AS_OF.get())
            now = time.monotonic()
            with _CACHE_LOCK:
                hit = _CACHE.get(key)
                if hit and now - hit[0] < seconds:
                    return hit[1]
            value = fn(*args, **kwargs)
            with _CACHE_LOCK:
                _CACHE[key] = (now, value)
            return value

        return wrapper

    return deco


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


@ttl_cache(30)
def table_exists(st: Store, schema: str, table: str) -> bool:
    """Whether a table is visible to this store's role (cached briefly: it is asked many times per page)."""
    try:
        return st.table_exists(schema, table)
    except Exception:  # noqa: BLE001 - permission or missing schema => not visible
        return False


def read_table(
    st: Store,
    schema: str,
    table: str,
    where: str | None = None,
    order_by: str | None = None,
    limit: int | None = None,
    columns: Iterable[str] | None = None,
    ts: Iterable[str] = (),
) -> pd.DataFrame:
    """Read a table if it exists and is visible to this role; otherwise an empty DataFrame.

    `columns` narrows the projection (use it for tables with large JSON/text columns); `ts` names timestamp columns
    that are normalized to timezone-aware UTC (Databricks returns aware values, the local lake naive ones).
    """
    if not table_exists(st, schema, table):
        return pd.DataFrame()
    cols = ", ".join(columns) if columns else "*"
    sql = f"SELECT {cols} FROM {st.fq(schema, table)}"
    if where:
        sql += f" WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return as_utc(st.query(sql), *ts)


def query(st: Store, sql: str, ts: Iterable[str] = ()) -> pd.DataFrame:
    """Run a SELECT through the store (ACL-checked) and normalize timestamp columns."""
    return as_utc(st.query(sql), *ts)


def sql_str(value: str) -> str:
    """Quote a user-supplied value for a SQL string literal (identifiers are never user-supplied)."""
    return "'" + str(value).replace("'", "''") + "'"


# --------------------------------------------------------------------------------------------- scalar coercion
def is_missing(v: Any) -> bool:
    if v is None or v is pd.NaT or v is pd.NA:
        return True
    if isinstance(v, float | np.floating):
        return math.isnan(float(v))
    return False


def num(v: Any) -> float | None:
    """A finite float or None (NaN, NA, None, non-numeric strings)."""
    if is_missing(v) or isinstance(v, bool | np.bool_):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def integer(v: Any) -> int | None:
    f = num(v)
    return None if f is None else int(f)


def text(v: Any) -> str | None:
    """A non-empty string or None (None, NaN and '' all mean "not set")."""
    if is_missing(v):
        return None
    s = str(v)
    return s if s != "" else None


def boolean(v: Any) -> bool | None:
    if is_missing(v):
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


def as_utc(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    """Normalize the named timestamp columns (when present) to timezone-aware UTC datetimes."""
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df


def iso(v: Any) -> str | None:
    """ISO-8601 UTC string for a timestamp-like value, or None."""
    if is_missing(v):
        return None
    ts = pd.Timestamp(v)
    if pd.isna(ts):
        return None
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.isoformat()


def parse_ts(v: str | None) -> pd.Timestamp | None:
    """Parse an ISO-8601 string (tolerating 'Z' and a missing offset) to a UTC Timestamp, or None."""
    if not v:
        return None
    try:
        ts = pd.Timestamp(str(v).strip())
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def col(df: pd.DataFrame, name: str, default: Any = None) -> pd.Series:
    """A column by name, or a constant Series when the table lacks it (tables written by other jobs may drift)."""
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index, dtype=object)


def rows(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> list of plain dicts (values untouched; use the scalar helpers to read them)."""
    return df.to_dict("records") if len(df) else []


def loads(s: Any, default: Any = None) -> Any:
    """Tolerant json.loads for JSON strings stored in tables (None, NaN, empty, or truncated text -> default)."""
    if is_missing(s) or s == "":
        return default
    if isinstance(s, dict | list):
        return s
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


_CODE_RE = re.compile(r"^[A-Za-z0-9._:\-]+$")


def safe_token(value: str) -> bool:
    """Whether a path/query token is a plain identifier (no separators, traversal or whitespace)."""
    return bool(value) and bool(_CODE_RE.match(value)) and ".." not in value


# --------------------------------------------------------------------------------------------- JSON conversion
def to_jsonable(obj: Any) -> Any:
    """Convert pandas/numpy values (NaN, NaT, Timestamps, numpy scalars) into JSON-safe Python values."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set | frozenset):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, pd.DataFrame):
        return [to_jsonable(r) for r in obj.to_dict("records")]
    if isinstance(obj, pd.Timestamp | datetime):
        if pd.isna(obj):
            return None
        ts = pd.Timestamp(obj)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating | float):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if obj is pd.NaT or (not isinstance(obj, str) and pd.api.types.is_scalar(obj) and pd.isna(obj)):
        return None
    return obj


def records(df: pd.DataFrame) -> list[dict]:
    return to_jsonable(df) if len(df) else []


class SafeJSONResponse(JSONResponse):
    """JSON response that never fails on NaN/Inf or pandas/numpy leftovers: they become null / plain values."""

    def render(self, content: Any) -> bytes:
        return json.dumps(to_jsonable(content), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


# The `def` query parameter (a definition version or unique prefix; default: the active definition). `def` is a Python
# keyword, so handlers bind it through this alias: `def handler(version: str | None = DEF_PARAM)`.
DEF_PARAM = Query(None, alias="def", description="definition version (default: the active definition)")


def api_router() -> APIRouter:
    """A router whose responses are sanitized by SafeJSONResponse."""
    return APIRouter(default_response_class=SafeJSONResponse)


def unavailable(reason: str, requires: list[str]) -> dict:
    return {"available": False, "reason": reason, "requires": requires}


def short(version: str | None) -> str | None:
    return None if not version else str(version)[:8]
