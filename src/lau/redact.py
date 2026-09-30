"""Credential redaction for anything that is logged, traced, or sent to an agent."""

from __future__ import annotations

import re
from typing import Any

# Patterns for credential-like strings. Kept in sync with tests/unit/test_no_secrets_in_repo.py.
SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"dapi[0-9a-f]{32}(-\d)?"),  # Databricks PAT
    re.compile(r"dose[0-9a-f]{32}"),  # Databricks OAuth SP secret
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),  # Anthropic key
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"(?i)(client_secret|token|password|api_key)\s*[=:]\s*['\"]?[^\s'\",}]{8,}"),
]

SENSITIVE_KEYS = {"token", "client_secret", "password", "api_key", "authorization", "secret", "access_token"}


def redact_text(text: str) -> str:
    for pat in SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def redact(obj: Any) -> Any:
    """Recursively redact dict/list/str payloads."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if str(k).lower() in SENSITIVE_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [redact(v) for v in obj]
    return obj
