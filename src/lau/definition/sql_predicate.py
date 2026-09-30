"""Sandbox for `custom_sql_predicate` (and agent-proposed feature expressions).

An expression is accepted only if it parses as a single scalar SQL expression that references allow-listed
columns and allow-listed functions: no subqueries, no table references, no star, no DDL/DML, bounded length.
Evaluation happens in an in-memory DuckDB over a pandas frame that contains only the allowed columns.
"""

from __future__ import annotations

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp

MAX_LEN = 500

# Columns a default-definition predicate may reference (one row = one loan-month of performance).
PERFORMANCE_COLUMNS = {
    "mob",
    "status",
    "dpd",
    "balance",
    "past_due_amount",
    "scheduled_payment",
    "payment_amount",
    "charge_off_flag",
    "bankruptcy_flag",
    "settlement_flag",
    "forbearance_flag",
    "payoff_flag",
    "fraud_flag",
    "deceased_flag",
}

ALLOWED_FUNCS = {
    exp.Abs,
    exp.Coalesce,
    exp.Greatest,
    exp.Least,
    exp.Ln,
    exp.Log,
    exp.Sqrt,
    exp.Round,
    exp.Floor,
    exp.Ceil,
    exp.Lower,
    exp.Upper,
    exp.Length,
    exp.If,
    exp.Case,
    exp.Cast,
    exp.Nullif,
    exp.Exp,
    exp.Pow,
    exp.Sign,
}
ALLOWED_NODES = (
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.Boolean,
    exp.Null,
    exp.Paren,
    exp.Neg,
    exp.Not,
    exp.And,
    exp.Or,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Is,
    exp.In,
    exp.Between,
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
    exp.Mod,
    exp.DataType,
    exp.Tuple,
    exp.If,
    exp.Case,
    exp.Like,
    exp.DPipe,
)


class UnsafeExpressionError(ValueError):
    pass


def validate_expression(sql: str, allowed_columns: set[str]) -> exp.Expression:
    if not isinstance(sql, str) or not sql.strip():
        raise UnsafeExpressionError("empty expression")
    if len(sql) > MAX_LEN:
        raise UnsafeExpressionError(f"expression longer than {MAX_LEN} chars")
    if ";" in sql:
        raise UnsafeExpressionError("multiple statements are not allowed")
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except sqlglot.errors.ParseError as e:
        raise UnsafeExpressionError(f"cannot parse: {e}") from e
    if isinstance(tree, exp.Query | exp.Command | exp.Create | exp.Insert | exp.Delete | exp.Update | exp.Drop):
        raise UnsafeExpressionError("statements are not allowed; provide a scalar expression")
    for node in tree.walk():
        if isinstance(node, exp.Subquery | exp.Select | exp.Table | exp.Star | exp.Anonymous):
            raise UnsafeExpressionError(f"disallowed construct: {type(node).__name__}")
        # Structural nodes (connectors, comparisons, arithmetic) are allowed even though some subclass exp.Func.
        if isinstance(node, ALLOWED_NODES):
            pass
        elif isinstance(node, exp.Func):
            if type(node) not in ALLOWED_FUNCS:
                raise UnsafeExpressionError(f"function not allowed: {node.sql()[:40]}")
        else:
            raise UnsafeExpressionError(f"disallowed construct: {type(node).__name__}")
        if isinstance(node, exp.Column):
            if node.table:
                raise UnsafeExpressionError("qualified column references are not allowed")
            if node.name.lower() not in allowed_columns:
                raise UnsafeExpressionError(f"column not allowed: {node.name}")
    return tree


def normalize_predicate(sql: str) -> str:
    """Validate against performance columns and return canonical SQL (so formatting doesn't change the hash)."""
    tree = validate_expression(sql, PERFORMANCE_COLUMNS)
    return tree.sql(dialect="duckdb", normalize=True)


def evaluate_expression(df: pd.DataFrame, sql: str, allowed_columns: set[str]) -> pd.Series:
    """Evaluate a validated expression row-wise over df (only allowed columns are visible)."""
    validate_expression(sql, allowed_columns)
    cols = [c for c in df.columns if c.lower() in allowed_columns]
    frame = df[cols].reset_index(drop=True)
    con = duckdb.connect()
    try:
        con.register("t", frame)
        out = con.execute(f"SELECT ({sql}) AS v FROM t").df()["v"]
    finally:
        con.close()
    out.index = df.index
    return out
