"""Notifications for the local console: high alerts, decisions waiting for a person, finished cycles and verdict
changes.

Checked after every mirror sync. The first check only records what already exists (no flood on start-up); later checks
notify about what is new, as macOS desktop notifications, and keep the last 100 in a log that Settings shows.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from lau.settings import get_settings

MAX_LOG = 100
MAX_PER_CHECK = 5


def _path() -> Path:
    return get_settings().local_lake / "_notifications.json"


def _load() -> dict:
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {"initialized": False, "seen": {}, "log": []}


def _save(state: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=1, default=str))


def current_items() -> dict[str, dict[str, dict]]:
    """{kind: {id: {title, body, href}}} for everything worth a notification right now."""
    from lau.console.services import approvals, ledger, ops

    out: dict[str, dict[str, dict]] = {"alert": {}, "waiting": {}, "cycle": {}, "verdict": {}}
    for a in ops.alerts():
        if a["current"] and not a["acknowledged"] and a["severity"] == "high":
            out["alert"][a["id"]] = {
                "title": "High alert",
                "body": ops.alert_title(a["kind"], a["subject"], a["value"]),
                "href": "/alerts",
            }
    for w in approvals.waiting_items():
        out["waiting"][w["id"]] = {"title": "Decision waiting", "body": w["title"], "href": w["href"]}
    df = ops.cycles()
    for r in df.to_dict("records") if len(df) else []:
        s = ops.cycle_summary(r)
        if s["status"] not in ("running", "abandoned"):
            body = f"Cycle {s['cycle_id']} {s['status'].replace('_', ' ')}"
            if s["challenger"]:
                body += f"; challenger v{s['challenger']} " + (
                    "passed validation" if s["challenger_passed_validation"] else "did not pass validation"
                )
            out["cycle"][s["cycle_id"]] = {
                "title": "Improvement cycle finished",
                "body": body,
                "href": f"/history/cycles/{s['cycle_id']}",
            }
    row = ledger.latest()
    if row:
        out["verdict"][f"{row['code']}:{row['best_known_key']}"] = {
            "title": "Improvement verdict changed",
            "body": row["title"],
            "href": "/progress",
        }
    return out


def check(send=None) -> list[dict]:
    """Notify about items not seen before; returns the new log entries."""
    from lau.console.snapshot import desktop_notify

    send = send or desktop_notify
    state = _load()
    items = current_items()
    if not state.get("initialized"):
        state.update(initialized=True, seen={k: sorted(v) for k, v in items.items()})
        _save(state)
        return []
    new: list[dict] = []
    for kind, found in items.items():
        seen = set(state["seen"].get(kind, []))
        for ident, item in found.items():
            if ident not in seen:
                new.append({"kind": kind, "id": ident, **item})
        state["seen"][kind] = sorted(set(found) | (seen if kind != "verdict" else set()))
    now = datetime.now(UTC).isoformat()
    shown = new[:MAX_PER_CHECK]
    for n in shown:
        n["ts"] = now
        n["delivered"] = bool(send(n["title"], n["body"]))
    if len(new) > MAX_PER_CHECK:
        rest = len(new) - MAX_PER_CHECK
        extra = {
            "kind": "summary",
            "id": now,
            "title": "More updates",
            "body": f"{rest} more updates in the console",
            "href": "/",
            "ts": now,
        }
        extra["delivered"] = bool(send(extra["title"], extra["body"]))
        shown.append(extra)
    state["log"] = (shown + state.get("log", []))[:MAX_LOG]
    _save(state)
    return shown


def recent(limit: int = 30) -> list[dict]:
    return _load().get("log", [])[:limit]
