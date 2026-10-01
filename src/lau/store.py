"""Storage abstraction: one API over Unity Catalog (Databricks SQL warehouse) and a local DuckDB lake.

Both backends:
  * use identical three-part names (`catalog.schema.table`), so the same SQL runs in both;
  * enforce the ACL from lau.governance.grants for the Store's role *before* executing (defense in depth; on
    Databricks UC grants enforce it again at the platform level).

Writes of DataFrames on Databricks go through a UC volume (`<schema>.landing`): parquet upload via the Files API,
then `CREATE TABLE AS / INSERT ... SELECT FROM read_files(...)`, then the staged file is deleted.
"""

from __future__ import annotations

import io
import threading
import time
import uuid
from abc import ABC, abstractmethod
from typing import Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import sqlglot
from sqlglot import exp

from lau.governance.grants import can_read, can_write
from lau.settings import Settings, get_settings

WriteMode = Literal["overwrite", "append", "replace_partition"]

LANDING_VOLUME = "landing"


class AccessDeniedError(PermissionError):
    """Raised when a role touches an object its grants do not allow (mirrors UC PERMISSION_DENIED)."""


_WRITE_EXPRS = (exp.Insert, exp.Create, exp.Delete, exp.Update, exp.Merge, exp.Drop, exp.Alter, exp.TruncateTable)


def referenced_tables(sql: str, dialect: str = "databricks") -> tuple[list[exp.Table], list[exp.Table]]:
    """Return (read_tables, write_tables) referenced by a SQL string. CTE names are excluded."""
    reads: list[exp.Table] = []
    writes: list[exp.Table] = []
    for stmt in sqlglot.parse(sql, read=dialect):
        if stmt is None:
            continue
        cte_names = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE)}
        target: exp.Table | None = None
        if isinstance(stmt, _WRITE_EXPRS):
            node = stmt.this
            if isinstance(node, exp.Schema):
                node = node.this
            if isinstance(node, exp.Table):
                target = node
                writes.append(node)
        for t in stmt.find_all(exp.Table):
            if t is target or not t.name or t.name.lower() in cte_names:
                continue
            reads.append(t)
    return reads, writes


class Store(ABC):
    backend: str

    def __init__(self, role: str, settings: Settings | None = None) -> None:
        self.role = role
        self.s = settings or get_settings()

    # ---- ACL -----------------------------------------------------------------------------------------
    def _resolve(self, t: exp.Table) -> tuple[str | None, str]:
        schema = t.db
        if not schema:
            raise AccessDeniedError(f"Unqualified table reference '{t.name}' is not allowed; use catalog.schema.table")
        if t.catalog and t.catalog.lower() != self.s.catalog.lower():
            if t.catalog.lower() == "system" and self.role == "admin":
                return "system", t.name
            raise AccessDeniedError(f"[{self.role}] catalog '{t.catalog}' is outside this project")
        key = self.s.schema_key_of(schema)
        if key is None:
            raise AccessDeniedError(f"[{self.role}] schema '{schema}' is not a project schema")
        return key, t.name

    def check_sql(self, sql: str) -> None:
        if self.role == "admin":
            return
        try:
            reads, writes = referenced_tables(sql, "duckdb" if self.backend == "local" else "databricks")
        except sqlglot.errors.ParseError as e:
            raise AccessDeniedError(f"Unparseable SQL rejected: {e}") from e
        for t in reads:
            key, name = self._resolve(t)
            if not can_read(self.role, key, name):
                raise AccessDeniedError(f"PERMISSION_DENIED: role '{self.role}' cannot read {key}.{name}")
        for t in writes:
            key, name = self._resolve(t)
            if not can_write(self.role, key, name):
                raise AccessDeniedError(f"PERMISSION_DENIED: role '{self.role}' cannot write {key}.{name}")

    def check_write(self, key: str, table: str) -> None:
        if not can_write(self.role, key, table):
            raise AccessDeniedError(f"PERMISSION_DENIED: role '{self.role}' cannot write {key}.{table}")

    def check_read(self, key: str, table: str) -> None:
        if not can_read(self.role, key, table):
            raise AccessDeniedError(f"PERMISSION_DENIED: role '{self.role}' cannot read {key}.{table}")

    # ---- API -----------------------------------------------------------------------------------------
    def fq(self, key: str, table: str) -> str:
        return self.s.fq(key, table)

    def query(self, sql: str) -> pd.DataFrame:
        self.check_sql(sql)
        return self._query(sql)

    def execute(self, sql: str) -> None:
        self.check_sql(sql)
        self._execute(sql)

    def read_table(
        self, key: str, table: str, where: str | None = None, columns: list[str] | None = None
    ) -> pd.DataFrame:
        cols = ", ".join(f"`{c}`" if self.backend != "local" else f'"{c}"' for c in columns) if columns else "*"
        sql = f"SELECT {cols} FROM {self.fq(key, table)}" + (f" WHERE {where}" if where else "")
        return self.query(sql)

    def write_df(
        self,
        key: str,
        table: str,
        df: pd.DataFrame,
        mode: WriteMode = "overwrite",
        partition: dict[str, str] | None = None,
    ) -> None:
        """Write a DataFrame. replace_partition deletes rows matching `partition` then appends."""
        self.check_write(key, table)
        df = _normalize_df(df)
        if mode == "replace_partition":
            if not partition:
                raise ValueError("replace_partition requires partition={col: value}")
            if self.table_exists(key, table):
                cond = " AND ".join(f"{c} = '{_esc(v)}'" for c, v in partition.items())
                self._execute(f"DELETE FROM {self.fq(key, table)} WHERE {cond}")
            mode = "append"
        self._write_df(key, table, df, mode)

    @abstractmethod
    def table_exists(self, key: str, table: str) -> bool: ...

    @abstractmethod
    def _query(self, sql: str) -> pd.DataFrame: ...

    @abstractmethod
    def _execute(self, sql: str) -> None: ...

    @abstractmethod
    def _write_df(self, key: str, table: str, df: pd.DataFrame, mode: str) -> None: ...

    def create_view(self, key: str, name: str, select_sql: str, comment: str | None = None) -> None:
        self.check_write(key, name)
        self._execute(f"CREATE OR REPLACE VIEW {self.fq(key, name)} AS {select_sql}")

    def drop_table(self, key: str, table: str) -> None:
        self.check_write(key, table)
        self._execute(f"DROP TABLE IF EXISTS {self.fq(key, table)}")


def _esc(v: str) -> str:
    return str(v).replace("'", "''")


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Make dtypes portable across DuckDB and Delta (no nanosecond timestamps, no pandas-extension objects)."""
    out = df.drop(columns=[c for c in df.columns if c == "_rescued_data"]).copy()
    for c in out.columns:
        dt = out[c].dtype
        if pd.api.types.is_datetime64_any_dtype(dt):
            out[c] = pd.to_datetime(out[c]).dt.tz_localize(None).astype("datetime64[us]")
        elif isinstance(dt, pd.CategoricalDtype):
            out[c] = out[c].astype("object")
        elif pd.api.types.is_bool_dtype(dt) and out[c].isna().any():
            out[c] = out[c].astype("object")
        if out[c].dtype == object and out[c].isna().all():
            # an all-null column would otherwise be typed NULL/INT by DuckDB/read_files; ids/text are strings
            out[c] = out[c].astype("string")
    return out


# ---------------------------------------------------------------------------------------------------------
# Local DuckDB backend
# ---------------------------------------------------------------------------------------------------------
_DUCK_LOCK = threading.RLock()
_DUCK_CONNS: dict[str, object] = {}


def _duck(settings: Settings):
    import duckdb

    path = str(settings.local_lake / "lake.duckdb")
    with _DUCK_LOCK:
        con = _DUCK_CONNS.get(path)
        if con is None:
            con = duckdb.connect()
            con.execute(f"ATTACH '{path}' AS {settings.catalog}")
            _DUCK_CONNS[path] = con
        return con


def reset_local_connections() -> None:
    with _DUCK_LOCK:
        for con in _DUCK_CONNS.values():
            con.close()  # type: ignore[attr-defined]
        _DUCK_CONNS.clear()


class LocalStore(Store):
    backend = "local"

    def __init__(self, role: str, settings: Settings | None = None) -> None:
        super().__init__(role, settings)
        self.con = _duck(self.s)

    def _translate(self, sql: str) -> str:
        # Allow Databricks-style backticks in shared SQL.
        return sql.replace("`", '"')

    def check_sql(self, sql: str) -> None:
        super().check_sql(self._translate(sql))

    def ensure_schemas(self) -> None:
        for key in self.s.project.schemas.model_fields:
            self.con.execute(f"CREATE SCHEMA IF NOT EXISTS {self.s.catalog}.{self.s.schema(key)}")

    def table_exists(self, key: str, table: str) -> bool:
        with _DUCK_LOCK:
            r = self.con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_catalog = ? AND table_schema = ? "
                "AND table_name = ?",
                [self.s.catalog, self.s.schema(key), table],
            ).fetchone()
        return bool(r and r[0])

    def _query(self, sql: str) -> pd.DataFrame:
        with _DUCK_LOCK:
            return self.con.execute(self._translate(sql)).df()

    def _execute(self, sql: str) -> None:
        with _DUCK_LOCK:
            self.con.execute(self._translate(sql))

    def _write_df(self, key: str, table: str, df: pd.DataFrame, mode: str) -> None:
        fq = self.fq(key, table)
        name = f"_df_{uuid.uuid4().hex[:8]}"
        with _DUCK_LOCK:
            self.con.execute(f"CREATE SCHEMA IF NOT EXISTS {self.s.catalog}.{self.s.schema(key)}")
            self.con.register(name, pa.Table.from_pandas(df, preserve_index=False))
            try:
                if mode == "overwrite" or not self.table_exists(key, table):
                    self.con.execute(f"CREATE OR REPLACE TABLE {fq} AS SELECT * FROM {name}")
                else:
                    self.con.execute(f"INSERT INTO {fq} BY NAME SELECT * FROM {name}")
            finally:
                self.con.unregister(name)


# ---------------------------------------------------------------------------------------------------------
# Databricks backend (SQL warehouse + UC volumes), one identity per Store
# ---------------------------------------------------------------------------------------------------------
class DatabricksStore(Store):
    backend = "databricks"

    def __init__(self, role: str, settings: Settings | None = None) -> None:
        super().__init__(role, settings)
        from databricks.sdk import WorkspaceClient

        from lau.credentials import databricks_config

        self.cfg = databricks_config(role)
        self.w = WorkspaceClient(config=self.cfg)
        self._conn = None
        # One statement at a time per identity: agent tools run in worker threads (parallel tool calls) and the
        # orchestrator's liveness writer runs beside them; the SQL connection is not shared concurrently.
        self._lock = threading.RLock()
        if not self.s.state.warehouse_id:
            raise RuntimeError("No warehouse_id in .lau/workspace_state.json; run `lau init` first.")

    @property
    def conn(self):
        if self._conn is None:
            from databricks import sql as dbsql

            cfg = self.cfg
            self._conn = dbsql.connect(
                server_hostname=cfg.host.replace("https://", "").rstrip("/"),
                http_path=f"/sql/1.0/warehouses/{self.s.state.warehouse_id}",
                credentials_provider=lambda: cfg.authenticate,
            )
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _run(self, sql: str, fetch: bool):
        from lau import cost

        with self._lock:
            t0 = time.time()
            with self.conn.cursor() as cur:
                cur.execute(sql)
                result = cur.fetchall_arrow().to_pandas() if fetch else None
            cost.record_warehouse_seconds(time.time() - t0)
        return result

    def table_exists(self, key: str, table: str) -> bool:
        try:
            return bool(self.w.tables.exists(self.fq(key, table)).table_exists)
        except Exception:  # noqa: BLE001 - missing schema or no privilege -> treat as not visible
            return False

    def _query(self, sql: str) -> pd.DataFrame:
        return self._run(sql, fetch=True)

    def _execute(self, sql: str) -> None:
        self._run(sql, fetch=False)

    def _write_df(self, key: str, table: str, df: pd.DataFrame, mode: str) -> None:
        schema = self.s.schema(key)
        folder = f"/Volumes/{self.s.catalog}/{schema}/{LANDING_VOLUME}/{uuid.uuid4().hex}"
        buf = io.BytesIO()
        pq.write_table(
            pa.Table.from_pandas(df, preserve_index=False), buf, coerce_timestamps="us", allow_truncated_timestamps=True
        )
        buf.seek(0)
        path = f"{folder}/part-0.parquet"
        self.w.files.upload(path, buf, overwrite=True)
        # read_files adds a `_rescued_data` column; exclude it so tables contain exactly the DataFrame's columns
        src = f"(SELECT * EXCEPT (_rescued_data) FROM read_files('{folder}/', format => 'parquet'))"
        fq = self.fq(key, table)
        try:
            with self._lock:  # the existence check and the write belong together
                self._create_or_insert(key, table, fq, src, mode)
        finally:
            try:
                self.w.files.delete(path)
                self.w.files.delete_directory(folder)
            except Exception:  # noqa: BLE001, S110 - best-effort cleanup of the staging file
                pass

    def _create_or_insert(self, key: str, table: str, fq: str, src: str, mode: str) -> None:
        if mode == "overwrite" or not self.table_exists(key, table):
            self._execute(f"CREATE OR REPLACE TABLE {fq} AS SELECT * FROM {src}")
        else:
            self._execute(f"INSERT INTO {fq} BY NAME SELECT * FROM {src}")


_STORES: dict[tuple[str, str], Store] = {}


def get_store(role: str) -> Store:
    s = get_settings()
    key = (s.project.backend, role)
    if key not in _STORES:
        _STORES[key] = LocalStore(role, s) if s.project.backend == "local" else DatabricksStore(role, s)
    return _STORES[key]


def clear_store_cache() -> None:
    for st in _STORES.values():
        if isinstance(st, DatabricksStore):
            st.close()
    _STORES.clear()
