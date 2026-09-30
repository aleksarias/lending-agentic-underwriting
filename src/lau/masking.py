"""Pluggable PII masking layer.

Every tool result is passed through a Masker before an agent sees it. In dev (synthetic data) the default is
IdentityMasker; with environment=prod the default flips to HashingMasker. The salt for hashing comes from the
LAU_MASKING_SALT env var (never from config).
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Protocol

import pandas as pd

FREE_TEXT_PATTERNS = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b"),
}


class Masker(Protocol):
    name: str

    def mask_frame(self, df: pd.DataFrame) -> pd.DataFrame: ...

    def mask_text(self, text: str) -> str: ...


class IdentityMasker:
    name = "identity"

    def mask_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def mask_text(self, text: str) -> str:
        return text


class _ColumnMasker:
    def __init__(self, pii_columns: list[str], patterns: list[str]) -> None:
        self.pii_columns = {c.lower() for c in pii_columns}
        self.patterns = [FREE_TEXT_PATTERNS[p] for p in patterns if p in FREE_TEXT_PATTERNS]

    def _mask_value(self, value: Any) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def mask_text(self, text: str) -> str:
        for pat in self.patterns:
            text = pat.sub(lambda m: str(self._mask_value(m.group(0))), text)
        return text

    def mask_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in out.columns:
            if col.lower() in self.pii_columns:
                out[col] = out[col].map(lambda v: None if pd.isna(v) else self._mask_value(v))
            elif out[col].dtype == object or pd.api.types.is_string_dtype(out[col]):
                out[col] = out[col].map(lambda v: self.mask_text(v) if isinstance(v, str) else v)
        return out


class HashingMasker(_ColumnMasker):
    """Deterministic salted hash: joins still work, raw values are not exposed."""

    name = "hash"

    def __init__(self, pii_columns: list[str], patterns: list[str], salt: str | None = None) -> None:
        super().__init__(pii_columns, patterns)
        self.salt = salt if salt is not None else os.environ.get("LAU_MASKING_SALT", "")

    def _mask_value(self, value: Any) -> str:
        digest = hashlib.sha256(f"{self.salt}|{value}".encode()).hexdigest()[:16]
        return f"h_{digest}"


class DropMasker(_ColumnMasker):
    name = "drop"

    def _mask_value(self, value: Any) -> str:
        return "[MASKED]"

    def mask_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        keep = [c for c in df.columns if c.lower() not in self.pii_columns]
        return super().mask_frame(df[keep])


def build_masker(masking_cfg: dict[str, Any], enabled: bool) -> Masker:
    if not enabled:
        return IdentityMasker()
    strategy = masking_cfg.get("strategy", "hash")
    cols = masking_cfg.get("pii_columns", [])
    pats = masking_cfg.get("free_text_patterns", [])
    if strategy == "drop":
        return DropMasker(cols, pats)
    if strategy == "identity":
        return IdentityMasker()
    return HashingMasker(cols, pats)


def get_masker() -> Masker:
    from lau.settings import get_settings

    s = get_settings()
    return build_masker(s.masking, s.masking_enabled)
