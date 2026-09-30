"""FastAPI dependencies: the read-only store, who is asking, and whether actions are enabled."""

from __future__ import annotations

import getpass
import os

from fastapi import HTTPException, Request

from lau.store import Store, get_store


def ui_store() -> Store:
    """Every read in the console goes through the read-only "ui" role."""
    return get_store("ui")


def actions_enabled() -> bool:
    """Human actions (gate, approve, promote, stop cycle, acknowledge) are off unless explicitly enabled.

    Local development: LAU_CONSOLE_ACTIONS=1. On Databricks Apps actions will run with the signed-in user's own
    identity (user authorization); until that is wired, they stay disabled there.
    """
    return os.environ.get("LAU_CONSOLE_ACTIONS", "") == "1"


def require_actions() -> None:
    if not actions_enabled():
        raise HTTPException(
            status_code=403, detail="Actions are disabled. Start the console with LAU_CONSOLE_ACTIONS=1."
        )


def current_user(request: Request) -> str:
    """Databricks Apps forwards the signed-in user's email in X-Forwarded-Email; locally we use the OS user."""
    return request.headers.get("x-forwarded-email") or request.headers.get("x-forwarded-user") or getpass.getuser()
