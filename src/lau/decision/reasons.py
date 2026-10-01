"""Adverse-action reason statements: model inputs mapped to the statements an applicant reads.

The mapping lives in config/reason_statements.yaml.

A feature without a mapping gets R99 and is reported as unmapped, so compliance can add it before notices go out.
"""

from __future__ import annotations

from functools import lru_cache

import yaml

from lau.settings import CONFIG_DIR

UNMAPPED = "R99"


@lru_cache(maxsize=1)
def library() -> dict:
    return yaml.safe_load((CONFIG_DIR / "reason_statements.yaml").read_text()) or {}


def statement_for(feature: str, lib: dict | None = None) -> tuple[str, str]:
    """(code, statement) for a model input."""
    lib = lib or library()
    statements = lib.get("statements", {})
    code = (lib.get("features") or {}).get(feature)
    if code is None:
        name = feature.lower()
        code = next((c for pattern, c in lib.get("patterns") or [] if pattern in name), UNMAPPED)
    return code, statements.get(code, statements.get(UNMAPPED, "Other factors in your application"))


def principal_reasons(contributions: dict[str, float], top_n: int, lib: dict | None = None) -> list[dict]:
    """The top features that pushed the PD up, as distinct statements (one statement is never listed twice)."""
    out: list[dict] = []
    seen: set[str] = set()
    for feature, value in sorted(contributions.items(), key=lambda kv: kv[1], reverse=True):
        if value <= 0 or len(out) >= top_n:
            break
        code, text = statement_for(feature, lib)
        if code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "statement": text, "feature": feature, "mapped": code != UNMAPPED})
    return out
