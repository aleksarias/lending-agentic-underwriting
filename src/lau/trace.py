"""Audit trail: every state-changing agent/tool action (who, what, cost, inputs, outputs), credentials redacted.

Rows are buffered in memory and flushed to `ops.agent_trace` by the harness/pipeline identity; agents have no
grant on `ops`, so they cannot alter their own trail.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from lau.redact import redact

MAX_FIELD_CHARS = 4000


def _dump(obj: Any) -> str:
    try:
        text = json.dumps(redact(obj), default=str)
    except TypeError:
        text = str(redact(str(obj)))
    return text[:MAX_FIELD_CHARS]


class TraceWriter:
    def __init__(self, cycle_id: str, definition_version: str) -> None:
        self.cycle_id = cycle_id
        self.definition_version = definition_version
        self._rows: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def log(
        self,
        agent: str,
        action: str,
        inputs: Any = None,
        outputs: Any = None,
        principal: str = "agent",
        state_changing: bool = True,
        cost_usd: float = 0.0,
        status: str = "ok",
    ) -> None:
        with self._lock:
            self._rows.append(
                {
                    "ts": datetime.now(UTC),
                    "cycle_id": self.cycle_id,
                    "definition_version": self.definition_version,
                    "agent": agent,
                    "principal": principal,
                    "action": action,
                    "state_changing": bool(state_changing),
                    "inputs": _dump(inputs),
                    "outputs": _dump(outputs),
                    "cost_usd": float(cost_usd),
                    "status": status,
                }
            )

    @property
    def rows(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def flush(self) -> int:
        from lau.store import get_store

        with self._lock:
            rows, self._rows = self._rows, []
        if rows:
            get_store("harness").write_df("ops", "agent_trace", pd.DataFrame(rows), mode="append")
        return len(rows)
