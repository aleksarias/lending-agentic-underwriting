"""Console snapshot: what the read-only ui role can see, published as parquet files to a Unity Catalog volume, so a
console running on a laptop mirrors the workspace through the Files API instead of keeping a SQL warehouse awake.

- `publish()` runs at the end of the daily job, after every cycle and after state-changing CLI commands. It reads
  AS THE UI IDENTITY, so Unity Catalog guarantees nothing beyond the console's grants leaves the workspace, and writes
  AS THE HARNESS IDENTITY (the ui identity cannot write anything). Unchanged tables are not re-uploaded.
- `publish_live()` is called by a running cycle every minute with its heartbeats and recent trace, straight from the
  orchestrator's memory (no extra warehouse queries).
- `Mirror` runs inside the local console: every minute it downloads the small manifest and pulls only the files whose
  hash changed into a local DuckDB lake, which the console reads. Files API calls need no warehouse.

Volume layout under /Volumes/<catalog>/<ops>/console/: manifest.json, tables/<schema>.<table>.parquet,
extras/jobs.json, extras/billing.parquet, extras/decision_api.json, live/current.json.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import platform
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from lau.settings import get_settings

log = logging.getLogger(__name__)

FORMAT = 1
MANIFEST = "manifest.json"
LIVE = "live/current.json"
UI_SCHEMAS = ("ops", "experiments", "feature_registry", "production")
MAX_ROWS = 200_000
SHADOW_RUNS_KEPT = 3  # row-level shadow scores: only the newest runs (the console shows aggregates)
DECISION_DAYS_KEPT = 90  # the decision log is append-only and grows daily: the console needs recent decisions
# Never copied to your machine: raw request payloads (the endpoint's inference table) and the simulator's truth.
SNAPSHOT_EXCLUDED_SUFFIXES = ("_payload",)
SNAPSHOT_EXCLUDED = {("ops", "sim_truth")}
LIVE_TRACE_ROWS = 400


# ------------------------------------------------------------------------------------------------------- volume
class Volume:
    """Files in the console volume."""

    def read(self, rel: str) -> bytes | None:  # pragma: no cover - interface
        raise NotImplementedError

    def write(self, rel: str, data: bytes) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class LocalVolume(Volume):
    """A folder standing in for the volume (local backend, tests)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def read(self, rel: str) -> bytes | None:
        p = self.root / rel
        return p.read_bytes() if p.is_file() else None

    def write(self, rel: str, data: bytes) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)


class UCVolume(Volume):
    """The Unity Catalog volume through the Files API (no SQL warehouse involved)."""

    def __init__(self, w, base: str) -> None:
        self.w, self.base = w, base.rstrip("/")

    def read(self, rel: str) -> bytes | None:
        from databricks.sdk.errors import NotFound

        try:
            return self.w.files.download(f"{self.base}/{rel}").contents.read()
        except NotFound:
            return None

    def write(self, rel: str, data: bytes) -> None:
        self.w.files.upload(f"{self.base}/{rel}", io.BytesIO(data), overwrite=True)


def volume_path() -> str:
    from lau.governance.uc_layout import CONSOLE_VOLUME

    s = get_settings()
    return f"/Volumes/{s.catalog}/{s.schema('ops')}/{CONSOLE_VOLUME}"


def local_volume_dir() -> Path:
    return Path(os.environ.get("LAU_CONSOLE_VOLUME_DIR", get_settings().local_lake / "_console_volume"))


def writer_volume() -> Volume:
    """Where snapshots are written: the harness identity on Databricks, a folder locally."""
    s = get_settings()
    if s.project.backend == "local":
        return LocalVolume(local_volume_dir())
    from lau.store import get_store

    return UCVolume(get_store("harness").w, volume_path())


def reader_volume() -> Volume:
    """Where the mirror reads from: the ui identity's Files API access, or a folder when LAU_CONSOLE_VOLUME_DIR
    is set."""
    if os.environ.get("LAU_CONSOLE_VOLUME_DIR"):
        return LocalVolume(local_volume_dir())
    from databricks.sdk import WorkspaceClient

    from lau.credentials import databricks_config

    return UCVolume(WorkspaceClient(config=databricks_config("ui")), volume_path())


# ------------------------------------------------------------------------------------------------------ helpers
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parquet(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="zstd")
    return buf.getvalue()


def _json(obj: Any) -> bytes:
    return json.dumps(obj, default=str, indent=1, sort_keys=True).encode()


def _now() -> datetime:
    return datetime.now(UTC)


def read_manifest(vol: Volume) -> dict | None:
    raw = vol.read(MANIFEST)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def snapshot_tables(st) -> list[tuple[str, str]]:
    """(schema key, table) for everything the ui role can read."""
    from lau.governance.grants import UI_READABLE_OBJECTS

    s = get_settings()
    out: list[tuple[str, str]] = []
    for key in UI_SCHEMAS:
        if st.backend == "local":
            df = st.con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_catalog = ? AND table_schema = ?",
                [s.catalog, s.schema(key)],
            ).df()
            names = sorted(df["table_name"])
        else:
            names = sorted(t.name for t in st.w.tables.list(catalog_name=s.catalog, schema_name=s.schema(key)))
        out += [
            (key, n) for n in names if (key, n) not in SNAPSHOT_EXCLUDED and not n.endswith(SNAPSHOT_EXCLUDED_SUFFIXES)
        ]
    for key, objs in UI_READABLE_OBJECTS.items():
        out += [(key, o) for o in objs if st.table_exists(key, o)]
    return out


def _table_sql(st, key: str, table: str) -> str:
    fq = st.fq(key, table)
    if (key, table) == ("ops", "shadow_scores"):
        newest = f"SELECT DISTINCT scored_at FROM {fq} ORDER BY scored_at DESC LIMIT {SHADOW_RUNS_KEPT}"
        return f"SELECT * FROM {fq} WHERE scored_at >= (SELECT min(scored_at) FROM ({newest}) newest)"
    if (key, table) == ("ops", "decisions"):
        since = f"(SELECT max(decided_at) FROM {fq}) - INTERVAL {DECISION_DAYS_KEPT} DAYS"
        return f"SELECT * FROM {fq} WHERE decided_at >= {since} ORDER BY decided_at DESC LIMIT {MAX_ROWS}"
    return f"SELECT * FROM {fq} LIMIT {MAX_ROWS}"


# ------------------------------------------------------------------------------------------- extras: jobs, billing
_DOW = {"SUN": 6, "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5}


def next_quartz_run(expr: str | None, after: datetime | None = None) -> datetime | None:
    """Next fire time (UTC) of a daily or weekly Quartz cron such as "0 0 6 * * ?" or "0 0 7 ? * MON"; None when the
    expression is more complex than that."""
    if not expr:
        return None
    parts = expr.split()
    if len(parts) < 6:
        return None
    sec, minute, hour, dom, month, dow = parts[:6]
    if not (sec.isdigit() and minute.isdigit() and hour.isdigit()) or month not in ("*", "?"):
        return None
    after = after or _now()
    base = after.replace(hour=int(hour), minute=int(minute), second=int(sec), microsecond=0)
    if dom in ("*", "?") and dow in ("*", "?"):
        return base if base > after else base + timedelta(days=1)
    if dom in ("*", "?") and dow.upper() in _DOW:
        target = _DOW[dow.upper()]
        days = (target - base.weekday()) % 7
        candidate = base + timedelta(days=days)
        return candidate if candidate > after else candidate + timedelta(days=7)
    return None


def endpoint_info(w) -> dict:
    """State of the decision endpoint as the ui identity sees it (CAN_VIEW, granted when the endpoint is created)."""
    name = get_settings().decisioning["endpoint"]["name"]
    try:
        ep = w.serving_endpoints.get(name)
    except Exception as e:  # noqa: BLE001 - not created yet, or not viewable
        if "does not exist" in str(e).lower() or "not found" in str(e).lower() or "NotFound" in type(e).__name__:
            return {"name": name, "exists": False}
        raise
    served = (ep.config.served_entities or []) if ep.config else []
    ready = str(getattr(ep.state, "ready", "") or "")
    update = str(getattr(ep.state, "config_update", "") or "")
    return {
        "name": name,
        "exists": True,
        "ready": ready.endswith("READY") and "NOT_READY" not in ready,
        "updating": update.endswith("IN_PROGRESS"),
        "update_failed": update.endswith("UPDATE_FAILED"),
        "served_version": served[0].entity_version if served else None,
        "workload_size": served[0].workload_size if served else None,
        "scale_to_zero": served[0].scale_to_zero_enabled if served else None,
        "checked_at": _now().isoformat(),
    }


def jobs_info(w) -> list[dict]:
    """Project jobs the ui identity may view (CAN_VIEW is granted by the bundle), with recent runs."""
    out = []
    for j in w.jobs.list():
        s = j.settings
        if not s or "lau-" not in (s.name or ""):
            continue
        sched, trig = s.schedule, s.trigger
        if sched is not None:
            paused = sched.pause_status is not None and sched.pause_status.value == "PAUSED"
            cron, tz = sched.quartz_cron_expression, sched.timezone_id
        else:
            paused = trig is None or (trig.pause_status is not None and trig.pause_status.value == "PAUSED")
            cron, tz = None, None
        runs = list(w.jobs.list_runs(job_id=j.job_id, limit=3, expand_tasks=False))
        last = runs[0] if runs else None
        result = None
        if last is not None and last.state is not None:
            result = (last.state.result_state.value if last.state.result_state else None) or (
                last.state.life_cycle_state.value if last.state.life_cycle_state else None
            )
        nxt = None if paused else next_quartz_run(cron) if (tz in (None, "UTC", "Etc/UTC")) else None
        out.append(
            {
                "name": s.name,
                "job_id": j.job_id,
                "paused": paused,
                "cron": cron,
                "timezone": tz,
                "next_run_at": nxt.isoformat() if nxt else None,
                "last_run_at": datetime.fromtimestamp(last.start_time / 1000, UTC).isoformat()
                if last and last.start_time
                else None,
                "last_result": result,
            }
        )
    return sorted(out, key=lambda x: x["name"])


BILLING_SQL = """
SELECT u.usage_date, u.billing_origin_product AS product, u.sku_name, u.usage_unit,
       sum(u.usage_quantity) AS quantity,
       sum(u.usage_quantity * coalesce(p.pricing.default, 0)) AS list_usd
FROM system.billing.usage u
LEFT JOIN system.billing.list_prices p
  ON u.sku_name = p.sku_name AND u.cloud = p.cloud AND u.usage_unit = p.usage_unit
 AND u.usage_start_time >= p.price_start_time
 AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
WHERE u.workspace_id = '{workspace_id}' AND u.usage_date >= date_sub(current_date(), 45)
GROUP BY u.usage_date, u.billing_origin_product, u.sku_name, u.usage_unit
"""


def billing_frame(st) -> tuple[pd.DataFrame | None, str | None]:
    """Workspace billing at list price for the last 45 days, or (None, reason) when the ui identity cannot read it."""
    try:
        ws = st.w.get_workspace_id()
        return st._query(BILLING_SQL.format(workspace_id=int(ws))), None
    except Exception as e:  # noqa: BLE001 - system tables need a grant from a metastore admin
        return None, f"system.billing is not readable by the console identity ({type(e).__name__})"


# ------------------------------------------------------------------------------------------------------ publish
def publish(
    source: str = "cli", log_fn: Callable[[str], None] = print, ui_store=None, volume: Volume | None = None
) -> dict:
    """Export every ui-readable table (and job schedules and billing on Databricks) to the console volume."""
    from lau.store import get_store

    st = ui_store or get_store("ui")
    vol = volume or writer_volume()
    previous = read_manifest(vol) or {}
    prev_tables = previous.get("tables", {})
    tables: dict[str, dict] = {}
    uploaded = 0
    for key, table in snapshot_tables(st):
        name = f"{key}.{table}"
        try:
            df = st.query(_table_sql(st, key, table))
        except Exception as e:  # noqa: BLE001 - one unreadable table must not stop the snapshot
            log_fn(f"snapshot: skipped {name}: {type(e).__name__}: {str(e)[:160]}")
            continue
        data = _parquet(df)
        digest = _sha(data)
        rel = f"tables/{name}.parquet"
        if prev_tables.get(name, {}).get("sha256") != digest:
            vol.write(rel, data)
            uploaded += 1
        tables[name] = {"file": rel, "rows": int(len(df)), "sha256": digest}
    extras: dict[str, Any] = {}
    if st.backend == "databricks":
        try:
            data = _json(jobs_info(st.w))
            vol.write("extras/jobs.json", data)
            extras["jobs"] = {"file": "extras/jobs.json", "sha256": _sha(data), "available": True}
        except Exception as e:  # noqa: BLE001
            extras["jobs"] = {"available": False, "reason": f"jobs are not viewable ({type(e).__name__})"}
        try:
            data = _json(endpoint_info(st.w))
            vol.write("extras/decision_api.json", data)
            extras["decision_api"] = {"file": "extras/decision_api.json", "sha256": _sha(data), "available": True}
        except Exception as e:  # noqa: BLE001
            reason = f"the endpoint is not viewable ({type(e).__name__})"
            extras["decision_api"] = {"available": False, "reason": reason}
        bill, reason = billing_frame(st)
        if bill is not None:
            data = _parquet(bill)
            vol.write("extras/billing.parquet", data)
            extras["billing"] = {"file": "extras/billing.parquet", "sha256": _sha(data), "available": True}
        else:
            extras["billing"] = {"available": False, "reason": reason}
    manifest = {
        "format": FORMAT,
        "published_at": _now().isoformat(),
        "source": source,
        "catalog": get_settings().catalog,
        "tables": tables,
        "extras": extras,
    }
    vol.write(MANIFEST, _json(manifest))
    log_fn(f"console snapshot: {len(tables)} tables ({uploaded} changed) -> {volume_path()}")
    return manifest


def publish_quietly(source: str, log_fn: Callable[[str], None] = print) -> None:
    """Best-effort publish after a state change (never fails the caller). Skipped locally and when disabled."""
    s = get_settings()
    if s.project.backend != "databricks" or os.environ.get("LAU_CONSOLE_SNAPSHOT", "1") == "0":
        return
    try:
        publish(source=source, log_fn=log_fn)
    except Exception as e:  # noqa: BLE001 - the console catches up at the next publish
        log_fn(f"warning: console snapshot not published ({type(e).__name__}: {str(e)[:160]})")


def live_enabled() -> bool:
    """Live cycle documents go to the workspace volume, or to a local folder when one is configured (tests)."""
    if os.environ.get("LAU_CONSOLE_LIVE", "1") == "0":
        return False
    return get_settings().project.backend == "databricks" or bool(os.environ.get("LAU_CONSOLE_VOLUME_DIR"))


def publish_live(cycle: dict, beats: list[dict], trace_rows: list[dict], volume: Volume | None = None) -> None:
    """A running (or just finished) cycle's state for the console, written from the orchestrator's memory."""
    vol = volume or writer_volume()
    doc = {
        "format": FORMAT,
        "updated_at": _now().isoformat(),
        "cycle": cycle,
        "beats": beats,
        "trace": trace_rows[-LIVE_TRACE_ROWS:],
    }
    vol.write(LIVE, _json(doc))


# -------------------------------------------------------------------------------------------------------- mirror
HEARTBEAT_COLUMNS = ["ts", "cycle_id", "step", "agent", "state", "experiments_used", "spent_usd"]
TRACE_COLUMNS = [
    "ts",
    "cycle_id",
    "definition_version",
    "agent",
    "principal",
    "action",
    "state_changing",
    "inputs",
    "outputs",
    "cost_usd",
    "status",
]
CYCLE_COLUMNS = ["cycle_id", "definition_version", "reason", "started_at", "status", "summary_json"]


class Mirror:
    """Keeps a local DuckDB lake equal to the latest console snapshot (and the live cycle, while one runs)."""

    def __init__(
        self,
        interval_s: float = 60.0,
        volume: Volume | None = None,
        notifier: Callable | None = None,
        target: Callable | None = None,
        directory: Path | None = None,
    ) -> None:
        self.interval_s = interval_s
        self._volume = volume
        self.notifier = notifier
        self._target = target  # returns the Store the mirror writes to (default: the admin store of this lake)
        self.dir = Path(directory) if directory else get_settings().local_lake
        self.index_path = self.dir / "_mirror_index.json"
        self.state: dict[str, Any] = {"published_at": None, "synced_at": None, "error": None, "live_updated_at": None}
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def volume(self) -> Volume:
        if self._volume is None:
            self._volume = reader_volume()
        return self._volume

    # ---- index of applied files ---------------------------------------------------------------------------
    def _index(self) -> dict:
        try:
            return json.loads(self.index_path.read_text())
        except (OSError, ValueError):
            return {"tables": {}, "extras": {}}

    def _save_index(self, idx: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(idx, indent=1))

    # ---- sync ---------------------------------------------------------------------------------------------
    def _store(self):
        from lau.store import get_store

        return self._target() if self._target else get_store("admin")

    def sync_once(self) -> dict:
        with self._lock:
            manifest = read_manifest(self.volume)
            changed: list[str] = []
            idx = self._index()
            if manifest and manifest.get("published_at") != idx.get("published_at"):
                st = self._store()
                st.ensure_schemas()
                for name, meta in manifest.get("tables", {}).items():
                    if idx["tables"].get(name) == meta["sha256"]:
                        continue
                    data = self.volume.read(meta["file"])
                    if data is None:
                        continue
                    key, table = name.split(".", 1)
                    df = pq.read_table(io.BytesIO(data)).to_pandas()
                    st.write_df(key, table, df, mode="overwrite")
                    idx["tables"][name] = meta["sha256"]
                    changed.append(name)
                for name, meta in (manifest.get("extras") or {}).items():
                    if not meta.get("available") or idx["extras"].get(name) == meta.get("sha256"):
                        continue
                    data = self.volume.read(meta["file"])
                    if data is not None:
                        (self.dir / f"_extras_{Path(meta['file']).name}").write_bytes(data)
                        idx["extras"][name] = meta["sha256"]
                        changed.append(name)
                idx["published_at"] = manifest.get("published_at")
                idx["manifest_extras"] = manifest.get("extras") or {}
                self._save_index(idx)
            live_changed = self._apply_live()
            self.state.update(
                published_at=idx.get("published_at"),
                synced_at=_now().isoformat(),
                error=None,
                live_changed=live_changed,
            )
        if changed or live_changed:
            from lau.console.util import clear_cache

            clear_cache()
            if self.notifier is not None:
                try:
                    self.notifier()
                except Exception as e:  # noqa: BLE001 - notifications are best effort
                    log.warning("notifications failed: %s", e)
        return {"changed": changed, "live": live_changed, "published_at": idx.get("published_at")}

    def _apply_live(self) -> bool:
        """Overlay the live cycle (heartbeats, trace, status) onto the mirror while the snapshot catches up."""
        raw = self.volume.read(LIVE)
        if not raw:
            return False
        try:
            doc = json.loads(raw)
        except ValueError:
            return False
        if doc.get("updated_at") == self.state.get("live_updated_at"):
            return False
        self.state["live_updated_at"] = doc.get("updated_at")
        cycle = doc.get("cycle") or {}
        cid = cycle.get("cycle_id")
        if not cid:
            return False
        idx = self._index()
        if idx.get("published_at") and doc.get("updated_at") and idx["published_at"] > doc["updated_at"]:
            return False  # the full snapshot is newer than the live document
        st = self._store()
        st.ensure_schemas()
        safe = str(cid).replace("'", "''")
        for table in ("cycles", "cycle_heartbeat", "agent_trace"):
            if st.table_exists("ops", table):
                st.execute(f"DELETE FROM {st.fq('ops', table)} WHERE cycle_id = '{safe}'")
        row = {c: cycle.get(c) for c in CYCLE_COLUMNS}
        row["started_at"] = pd.Timestamp(row["started_at"]) if row.get("started_at") else _now()
        row["summary_json"] = row.get("summary_json") or "{}"
        st.write_df("ops", "cycles", pd.DataFrame([row]), mode="append")
        if doc.get("beats"):
            beats = pd.DataFrame(doc["beats"]).reindex(columns=HEARTBEAT_COLUMNS)
            beats["ts"] = pd.to_datetime(beats["ts"], utc=True)
            beats["experiments_used"] = beats["experiments_used"].fillna(0).astype("int32")
            st.write_df("ops", "cycle_heartbeat", beats, mode="append")
        if doc.get("trace"):
            trace = pd.DataFrame(doc["trace"]).reindex(columns=TRACE_COLUMNS)
            trace["ts"] = pd.to_datetime(trace["ts"], utc=True)
            st.write_df("ops", "agent_trace", trace, mode="append")
        return True

    # ---- background loop ----------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="console-mirror", daemon=True)
        self._thread.start()

    def request_sync(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self) -> None:
        backoff = self.interval_s
        while not self._stop.is_set():
            try:
                self.sync_once()
                backoff = self.interval_s
            except Exception as e:  # noqa: BLE001 - keep serving the last good mirror
                self.state["error"] = f"{type(e).__name__}: {str(e)[:200]}"
                log.warning("console mirror sync failed: %s", self.state["error"])
                backoff = min(backoff * 2, 15 * 60)
            self._wake.wait(backoff)
            self._wake.clear()


_MIRROR: Mirror | None = None


def mirror() -> Mirror | None:
    return _MIRROR


def start_mirror(interval_s: float | None = None) -> Mirror:
    """Start the background sync (called by the console app when LAU_CONSOLE_MIRROR=1)."""
    global _MIRROR
    if _MIRROR is None:
        from lau.console import notifications

        secs = interval_s or float(os.environ.get("LAU_CONSOLE_SYNC_SECONDS", "60"))
        _MIRROR = Mirror(interval_s=secs, notifier=notifications.check)
        _MIRROR.start()
    return _MIRROR


def mirror_extra(name: str) -> bytes | None:
    """An extras file (jobs.json, billing.parquet) as last synced, or None."""
    p = get_settings().local_lake / f"_extras_{name}"
    return p.read_bytes() if p.is_file() else None


# ------------------------------------------------------------------------------------------- desktop notify
def desktop_notify(title: str, body: str) -> bool:
    """macOS notification (best effort); returns whether one was shown."""
    if platform.system() != "Darwin" or os.environ.get("LAU_CONSOLE_NOTIFY", "1") == "0":
        return False
    script = f"display notification {json.dumps(body[:240])} with title {json.dumps(title[:80])}"
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=10, capture_output=True)  # noqa: S603, S607
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def wait_until(predicate: Callable[[], bool], timeout_s: float = 10.0) -> bool:  # small helper for tests
    end = time.time() + timeout_s
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False
