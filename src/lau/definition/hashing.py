"""Content hash of the normalized definition = `definition_version`."""

from __future__ import annotations

import hashlib
import json

from lau.definition.schema import DefaultDefinition

# Bump when label-builder semantics change in a way that should invalidate every existing version.
LABEL_LOGIC_VERSION = "v1"
HASH_LEN = 12


def canonical_json(defn: DefaultDefinition) -> str:
    return json.dumps({"logic": LABEL_LOGIC_VERSION, **defn.semantic_dict()}, sort_keys=True, separators=(",", ":"))


def definition_version(defn: DefaultDefinition) -> str:
    return hashlib.sha256(canonical_json(defn).encode()).hexdigest()[:HASH_LEN]


def short(version: str) -> str:
    return version[:8]
