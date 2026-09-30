"""Tiny explicit DAG engine with fingerprint-based invalidation.

fingerprint(stage, version) = sha256(stage name, stage code_version,
                                     definition_version if the stage is definition-dependent,
                                     root input fingerprint (e.g. synthetic data version),
                                     fingerprints of all upstream stages)

A stage is FRESH when ops.pipeline_state holds a successful run with exactly that fingerprint. Therefore:
  * unchanged definition + unchanged data -> every stage fresh -> nothing runs (idempotent)
  * changed definition -> every definition-dependent stage (and everything downstream) is stale, in topo order
  * changed raw data -> curate and everything downstream is stale
"""

from __future__ import annotations

import hashlib
import json
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Stage:
    name: str
    func: Callable[[Any], dict]
    upstream: tuple[str, ...] = ()
    definition_dependent: bool = True
    code_version: str = "1"
    description: str = ""
    root_input: Callable[[Any], str] | None = None  # for source stages: returns an input fingerprint
    # Stages that do less in side-by-side (non-activating) compare builds must not look fresh after activation.
    mode_sensitive: bool = False


@dataclass
class StagePlan:
    name: str
    status: str  # fresh | stale
    reason: str
    fingerprint: str


@dataclass
class RunResult:
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    details: dict[str, dict] = field(default_factory=dict)


class StageFailedError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, stages: list[Stage]) -> None:
        self.stages = {s.name: s for s in stages}
        for s in stages:
            for u in s.upstream:
                if u not in self.stages:
                    raise ValueError(f"{s.name}: unknown upstream {u}")
        self.order = self._topo()

    def _topo(self) -> list[str]:
        seen: dict[str, int] = {}
        out: list[str] = []

        def visit(n: str) -> None:
            if seen.get(n) == 1:
                raise ValueError(f"cycle at {n}")
            if seen.get(n) == 2:
                return
            seen[n] = 1
            for u in self.stages[n].upstream:
                visit(u)
            seen[n] = 2
            out.append(n)

        for n in self.stages:
            visit(n)
        return out

    def downstream_of(self, names: set[str]) -> set[str]:
        out = set(names)
        changed = True
        while changed:
            changed = False
            for s in self.stages.values():
                if s.name not in out and set(s.upstream) & out:
                    out.add(s.name)
                    changed = True
        return out

    def definition_dependent(self) -> list[str]:
        dep = {s.name for s in self.stages.values() if s.definition_dependent}
        return [n for n in self.order if n in self.downstream_of(dep)]

    # ---- fingerprints --------------------------------------------------------------------------------
    def fingerprints(self, ctx) -> dict[str, str]:
        fps: dict[str, str] = {}
        for n in self.order:
            s = self.stages[n]
            payload = {
                "stage": n,
                "code": s.code_version,
                "definition": ctx.version if s.definition_dependent else "",
                "root": s.root_input(ctx) if s.root_input else "",
                "mode": ("active" if ctx.activate else "compare") if s.mode_sensitive else "",
                "upstream": [fps[u] for u in s.upstream],
            }
            fps[n] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
        return fps

    def plan(self, ctx, state: pd.DataFrame) -> list[StagePlan]:
        fps = self.fingerprints(ctx)
        done = set()
        if not state.empty:
            ok = state[state["status"] == "success"]
            done = set(zip(ok["stage"], ok["fingerprint"], strict=False))
        plans = []
        stale: set[str] = set()
        for n in self.order:
            s = self.stages[n]
            if (n, fps[n]) in done and not (set(s.upstream) & stale):
                plans.append(StagePlan(n, "fresh", "fingerprint matches a successful run", fps[n]))
            else:
                reason = (
                    ("upstream stale: " + ", ".join(sorted(set(s.upstream) & stale)))
                    if set(s.upstream) & stale
                    else ("new definition version" if s.definition_dependent else "inputs changed or never run")
                )
                plans.append(StagePlan(n, "stale", reason, fps[n]))
                stale.add(n)
        return plans

    def run(
        self,
        ctx,
        state_reader: Callable[[], pd.DataFrame],
        state_writer: Callable[[dict], None],
        only: set[str] | None = None,
        stop_before: set[str] | None = None,
    ) -> RunResult:
        result = RunResult()
        for p in self.plan(ctx, state_reader()):
            if only is not None and p.name not in only:
                continue
            if stop_before and p.name in stop_before:
                result.skipped.append(p.name)
                continue
            if p.status == "fresh":
                result.skipped.append(p.name)
                continue
            stage = self.stages[p.name]
            ctx.log(f"▶ {p.name}: {stage.description} ({p.reason})")
            t0 = time.time()
            started = datetime.now(UTC)
            try:
                details = stage.func(ctx) or {}
            except Exception as e:
                state_writer(
                    {
                        "stage": p.name,
                        "definition_version": ctx.version,
                        "fingerprint": p.fingerprint,
                        "status": "failed",
                        "started_at": started,
                        "finished_at": datetime.now(UTC),
                        "details": json.dumps({"error": str(e), "tb": traceback.format_exc()[-2000:]}),
                    }
                )
                raise StageFailedError(f"stage {p.name} failed: {e}") from e
            state_writer(
                {
                    "stage": p.name,
                    "definition_version": ctx.version,
                    "fingerprint": p.fingerprint,
                    "status": "success",
                    "started_at": started,
                    "finished_at": datetime.now(UTC),
                    "details": json.dumps(details, default=str)[:8000],
                }
            )
            ctx.log(f"  ✓ {p.name} in {time.time() - t0:.1f}s")
            result.ran.append(p.name)
            result.details[p.name] = details
        return result
