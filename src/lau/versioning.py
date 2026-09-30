"""Version ledger: a content hash for everything that shapes a cycle, appended to `ops.config_versions` on change.

Components
  thresholds, budgets, protected_classes, models, benchmarks   config/*.yaml, parsed then canonical-JSON hashed
  grants                                                        `lau.governance.grants.GRANTS`, sorted canonical form
  prompt:<role>                                                 `agents/prompts/_common.md` + `<role>.md`
  code                                                          git HEAD of the project root, plus a dirty marker

`record_config_versions` appends a row only for components whose latest recorded hash differs (or that were never
recorded), so the table is a change log: the console rebuilds the version vector at any instant from it.

"Dirty" looks only at what a cycle executes (`src/`, `pyproject.toml`, `uv.lock`). Files that agents or operators
rewrite as data (LESSONS.md, reports/, docs) would otherwise flip every clean checkout to dirty after one cycle.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from lau.governance import grants as grants_mod
from lau.settings import CONFIG_DIR, ROOT
from lau.store import Store, get_store

CONFIG_COMPONENTS = ("thresholds", "budgets", "protected_classes", "models", "benchmarks")
PROMPTS_DIR = Path(__file__).resolve().parent / "agents" / "prompts"
CODE_PATHS = ("src", "pyproject.toml", "uv.lock")
HASH_LEN = 12
MAX_DIRTY_FILES = 50


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:HASH_LEN]


def _os_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - containers without a passwd entry for the uid
        return os.environ.get("USER") or "unknown"


def _git(*args: str) -> str | None:
    """stdout of `git <args>` at the project root; None when git or the repository is unavailable.

    GIT_OPTIONAL_LOCKS=0 keeps `status`/`diff` from refreshing the index, so this read never contends with a
    commit someone is making at the same time.
    """
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],  # noqa: S607 - git is resolved from PATH on purpose
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


# ---------------------------------------------------------------------------------------------------------
def _config_version(name: str) -> tuple[str, str] | None:
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        return None
    content = _canonical(yaml.safe_load(path.read_text()) or {})
    return _digest(content), content


def _grants_version() -> tuple[str, str]:
    rows = sorted(
        (
            {"role": g.role, "level": g.level, "schema": g.schema, "obj": g.obj, "privileges": sorted(g.privileges)}
            for g in grants_mod.GRANTS
        ),
        key=_canonical,
    )
    content = _canonical(rows)
    return _digest(content), content


def _prompt_versions() -> dict[str, tuple[str, str]]:
    """One component per role file; the shared `_common.md` is part of every cycle role's hash."""
    from lau.agents.runner import STANDALONE_ROLES

    common_path = PROMPTS_DIR / "_common.md"
    common = common_path.read_text() if common_path.exists() else ""
    out: dict[str, tuple[str, str]] = {}
    for f in sorted(PROMPTS_DIR.glob("*.md")):
        if f.name.startswith("_"):
            continue
        # the template `runner.load_prompt` renders, before substitution
        text = f.read_text() if f.stem in STANDALONE_ROLES else common + "\n\n" + f.read_text()
        out[f"prompt:{f.stem}"] = (_digest(text), _canonical({"role": f.stem, "text": text}))
    return out


def _code_version() -> tuple[str, str]:
    """(hash, content): `<sha12>` when clean, `<sha12>-dirty-<digest8>` when code has uncommitted changes.

    The digest covers the tracked diff and the names of untracked files, so further uncommitted edits are a new
    version. Without git the hash is "unknown".
    """
    sha = (_git("rev-parse", "HEAD") or "").strip()
    if not sha:
        return "unknown", _canonical({"git_sha": None, "dirty": None})
    status = (_git("status", "--porcelain", "--", *CODE_PATHS) or "").rstrip()
    dirty_files = [ln.strip() for ln in status.splitlines() if ln.strip()]
    if not dirty_files:
        return sha[:HASH_LEN], _canonical({"git_sha": sha, "dirty": False})
    digest = _digest(status + "\n" + (_git("diff", "HEAD", "--", *CODE_PATHS) or ""))
    content = {
        "git_sha": sha,
        "dirty": True,
        "dirty_digest": digest,
        "dirty_files": dirty_files[:MAX_DIRTY_FILES],
        "scope": list(CODE_PATHS),
    }
    return f"{sha[:HASH_LEN]}-dirty-{digest[:8]}", _canonical(content)


def current_versions() -> dict[str, tuple[str, str]]:
    """component -> (hash, canonical content JSON) for what is on disk right now."""
    out = {name: v for name in CONFIG_COMPONENTS if (v := _config_version(name)) is not None}
    out["grants"] = _grants_version()
    out.update(_prompt_versions())
    out["code"] = _code_version()
    return out


# ---------------------------------------------------------------------------------------------------------
def recorded_versions(st: Store | None = None) -> dict[str, dict[str, Any]]:
    """component -> the latest row recorded in `ops.config_versions` (empty when nothing was recorded yet)."""
    st = st or get_store("harness")
    if not st.table_exists("ops", "config_versions"):
        return {}
    df = st.query(
        "SELECT component, version_hash, recorded_at, git_sha, recorded_by, reason "
        f"FROM {st.fq('ops', 'config_versions')}"
    )
    if df.empty:
        return {}
    latest = df.sort_values("recorded_at", kind="stable").groupby("component", sort=False).tail(1)
    return {str(r["component"]): r for r in latest.to_dict("records")}


def compare() -> list[dict[str, Any]]:
    """Current vs latest recorded hash per component; state is `same`, `changed` or `new` (never recorded)."""
    current, last = current_versions(), recorded_versions()
    rows = []
    for component, (version_hash, _content) in current.items():
        rec = last.get(component)
        state = "new" if rec is None else ("same" if rec["version_hash"] == version_hash else "changed")
        rows.append(
            {
                "component": component,
                "current": version_hash,
                "recorded": rec["version_hash"] if rec else None,
                "recorded_at": rec["recorded_at"] if rec else None,
                "state": state,
            }
        )
    return rows


def record_config_versions(reason: str, recorded_by: str | None = None) -> int:
    """Append a row for every component whose hash differs from its latest recorded one; returns rows written."""
    current = current_versions()
    last = recorded_versions()
    changed = [c for c, (h, _) in current.items() if c not in last or last[c]["version_hash"] != h]
    if not changed:
        return 0
    git_sha = json.loads(current.get("code", ("", "{}"))[1]).get("git_sha") or "unknown"
    now, who = datetime.now(UTC), recorded_by or _os_user()
    rows = [
        {
            "recorded_at": now,
            "component": c,
            "version_hash": current[c][0],
            "content_json": current[c][1],
            "git_sha": git_sha,
            "recorded_by": who,
            "reason": reason,
        }
        for c in changed
    ]
    get_store("harness").write_df("ops", "config_versions", pd.DataFrame(rows), mode="append")
    return len(rows)


def try_record_config_versions(reason: str, recorded_by: str | None = None, log: Callable[[str], None] = print) -> int:
    """`record_config_versions` for definition apply and cycle start: a failure is logged, never raised."""
    try:
        n = record_config_versions(reason, recorded_by)
    except Exception as e:  # noqa: BLE001 - the ledger must never break an apply or a cycle
        log(f"warning: could not record config versions ({type(e).__name__}: {e})")
        return 0
    if n:
        log(f"recorded {n} changed config component(s) in ops.config_versions ({reason})")
    return n
