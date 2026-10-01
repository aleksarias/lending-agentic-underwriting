"""LESSONS.md: versioned lessons, each tagged with the definition_version it was learned under.

Entry format (one per line under "## Lessons"):
  - [L-<id>] [def:<version>] [scope:definition-independent|definition-specific] [status:<status>] <text>

On definition change (pipeline stage `lessons`):
  * definition-independent lessons (e.g. leakage patterns) carry forward unchanged
  * definition-specific lessons learned under another version get status "unverified-under-<new v8>"
The file is rewritten only by code (curator tool / pipeline); agents cannot edit it directly.

Storage: on Databricks the lessons live in `ops.lessons` (the single copy shared by local runs, scheduled jobs and
the console); LESSONS.md is then a readable export, written when its location is writable. On the local backend the
file is the store. The first Databricks read imports LESSONS.md if the table does not exist yet.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from lau.settings import get_settings

HEADER = """# LESSONS

Versioned lessons distilled by the curator after each improvement cycle. Each entry is tagged with the
`definition_version` it was learned under. When the default definition changes, only entries marked
`scope:definition-independent` carry forward as-is; the rest are flagged `unverified-under-<version>`.

## Lessons
"""

LINE_RE = re.compile(
    r"^- \[(?P<id>L-[0-9a-f]+)\] \[def:(?P<def>[0-9a-f]+)\] \[scope:(?P<scope>[a-z-]+)\] "
    r"\[status:(?P<status>[a-z0-9-]+)\] (?P<text>.+)$"
)


@dataclass
class Lesson:
    id: str
    definition_version: str
    scope: str
    status: str
    text: str

    def line(self) -> str:
        return f"- [{self.id}] [def:{self.definition_version}] [scope:{self.scope}] [status:{self.status}] {self.text}"


def _in_table() -> bool:
    return get_settings().project.backend == "databricks"


def _read_file() -> list[Lesson]:
    p = get_settings().lessons_path
    if not p.exists():
        return []
    out = []
    for ln in p.read_text().splitlines():
        m = LINE_RE.match(ln.strip())
        if m:
            out.append(Lesson(m["id"], m["def"], m["scope"], m["status"], m["text"]))
    return out


def _write_file(lessons: list[Lesson]) -> None:
    body = "\n".join(le.line() for le in lessons)
    get_settings().lessons_path.write_text(HEADER + ("\n" + body + "\n" if body else "\n_(none yet)_\n"))


def read_lessons() -> list[Lesson]:
    if not _in_table():
        return _read_file()
    from lau.store import get_store

    st = get_store("harness")
    if not st.table_exists("ops", "lessons"):
        found = _read_file()
        if found:
            write_lessons(found)  # one-time import of LESSONS.md
        return found
    df = st.query(
        f"SELECT id, definition_version, scope, status, text, ord FROM {st.fq('ops', 'lessons')} ORDER BY ord"
    )
    return [
        Lesson(str(r.id), str(r.definition_version), str(r.scope), str(r.status), str(r.text)) for r in df.itertuples()
    ]


def write_lessons(lessons: list[Lesson]) -> None:
    if _in_table():
        import pandas as pd

        from lau.store import get_store

        rows = [
            {"ord": i, "id": le.id, "definition_version": le.definition_version, "scope": le.scope,
             "status": le.status, "text": le.text, "updated_at": datetime.now(UTC)}
            for i, le in enumerate(lessons)
        ]  # fmt: skip
        cols = ["ord", "id", "definition_version", "scope", "status", "text", "updated_at"]
        get_store("harness").write_df("ops", "lessons", pd.DataFrame(rows, columns=cols), mode="overwrite")
    try:
        _write_file(lessons)  # readable export (read-only in scheduled jobs, which is fine)
    except OSError:
        if not _in_table():
            raise


def add_lessons(entries: list[dict], version: str) -> list[Lesson]:
    lessons = read_lessons()
    new = []
    for e in entries:
        text = " ".join(str(e["text"]).split())[:400]
        scope = "definition-independent" if e.get("definition_independent") else "definition-specific"
        le = Lesson(f"L-{uuid.uuid4().hex[:6]}", version, scope, "active", text)
        lessons.append(le)
        new.append(le)
    write_lessons(lessons)
    return new


def set_statuses(updates: list[dict], version: str) -> list[str]:
    """Re-verified lessons: `active` (still holds under `version`) or `retired` (does not). Only lessons flagged
    unverified under this definition can change; returns the ids that changed."""
    pending = f"unverified-under-{version[:8]}"
    wanted = {str(u["id"]): str(u["status"]) for u in updates if u.get("status") in ("active", "retired")}
    lessons = read_lessons()
    changed = []
    for le in lessons:
        if le.id in wanted and le.status == pending:
            le.status = wanted[le.id]
            if le.status == "active":
                le.definition_version = version  # now verified under the active definition
            changed.append(le.id)
    if changed:
        write_lessons(lessons)
    return changed


def revalidate_for_definition(version: str) -> dict:
    lessons = read_lessons()
    flagged = carried = 0
    for le in lessons:
        if le.definition_version == version:
            if le.status.startswith("unverified-under-"):
                le.status = "active"
            continue
        if le.scope == "definition-independent":
            carried += 1
        elif not le.status.startswith("unverified-under-"):
            le.status = f"unverified-under-{version[:8]}"
            flagged += 1
    write_lessons(lessons)
    return {
        "carried_forward": carried,
        "flagged_unverified": flagged,
        "total": len(lessons),
        "ts": datetime.now(UTC).isoformat(),
    }


def lessons_for_prompt(version: str, limit: int = 30) -> str:
    rel = [le for le in read_lessons() if le.definition_version == version or le.scope == "definition-independent"]
    other = [le for le in read_lessons() if le not in rel]
    lines = [le.line() for le in rel[-limit:]]
    if other:
        lines.append(
            f"({len(other)} lesson(s) from other definitions are unverified under {version[:8]} and "
            "must not be relied on)"
        )
    return "\n".join(lines) or "(no lessons yet)"
