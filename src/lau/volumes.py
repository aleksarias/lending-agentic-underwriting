"""Files in Unity Catalog volumes (Files API, no SQL warehouse) or, on the local backend, folders standing in for them.

Used by the console snapshot (ops.console) and the simulated servicer's feed (simulation.servicer_feed).
"""

from __future__ import annotations

import io
from pathlib import Path


class Volume:
    def read(self, rel: str) -> bytes | None:  # pragma: no cover - interface
        raise NotImplementedError

    def write(self, rel: str, data: bytes) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def list(self, prefix: str = "") -> list[str]:  # pragma: no cover - interface
        """Relative paths of every file under `prefix`, sorted."""
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

    def list(self, prefix: str = "") -> list[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(
            str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file() and not p.name.endswith(".tmp")
        )


class UCVolume(Volume):
    """A Unity Catalog volume through the Files API."""

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

    def list(self, prefix: str = "") -> list[str]:
        from databricks.sdk.errors import NotFound

        out: list[str] = []

        def walk(path: str) -> None:
            try:
                entries = list(self.w.files.list_directory_contents(path))
            except NotFound:
                return
            for e in entries:
                if e.is_directory:
                    walk(e.path)
                else:
                    out.append(e.path[len(self.base) + 1 :])

        walk(f"{self.base}/{prefix}".rstrip("/"))
        return sorted(out)


def volume(schema_key: str, name: str, role: str = "harness") -> Volume:
    """The named volume as `role` (a folder under the local lake on the local backend)."""
    from lau.settings import get_settings

    s = get_settings()
    if s.project.backend == "local":
        return LocalVolume(s.local_lake / "_volumes" / s.schema(schema_key) / name)
    from lau.store import get_store

    return UCVolume(get_store(role).w, f"/Volumes/{s.catalog}/{s.schema(schema_key)}/{name}")
