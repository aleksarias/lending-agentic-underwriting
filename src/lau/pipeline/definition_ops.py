"""`default-definition plan | apply | compare` — the ONLY way a definition change enters the system.

plan   : diff vs the active version, affected stages, estimated cost, label-rate impact (computed in memory).
apply  : requires explicit confirmation (interactive) or a recorded approval for that exact hash (CI/job path);
         registers + activates the version, marks other versions' champions superseded, rebuilds stale stages.
compare: builds another definition side by side (no activation) and writes a comparison report.
"""

from __future__ import annotations

import getpass
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from lau import cost
from lau.definition import registry
from lau.definition.hashing import definition_version, short
from lau.definition.label_builder import build_labels, label_summary
from lau.definition.schema import DefaultDefinition, load_definition
from lau.pipeline.stages import PipelineContext, build_pipeline, read_state, write_state
from lau.settings import CONFIG_DIR, get_settings
from lau.store import get_store

DEFINITION_PATH = CONFIG_DIR / "default_definition.yaml"


@dataclass
class DefinitionPlan:
    version: str
    active: str | None
    diff: list[tuple[str, object, object]]
    stages: list[tuple[str, str, str]]  # (stage, status, reason)
    estimate: cost.CostEstimate
    impact: dict = field(default_factory=dict)

    @property
    def stale(self) -> list[str]:
        return [s for s, st, _ in self.stages if st == "stale"]

    @property
    def is_noop(self) -> bool:
        return self.version == self.active and not self.stale

    def render(self) -> str:
        lines = [f"Definition in YAML : {self.version}", f"Active definition  : {self.active or '(none)'}"]
        if self.version == self.active:
            lines.append("Definition unchanged.")
        else:
            lines.append("Changes:")
            lines += [f"  {k}: {o!r} -> {n!r}" for k, o, n in self.diff] or ["  (metadata only)"]
        lines.append("Stages:")
        lines += [f"  [{'REBUILD' if st == 'stale' else 'fresh  '}] {s} — {r}" for s, st, r in self.stages]
        if self.impact:
            i = self.impact
            lines.append("Label impact (in-memory, all approved loans):")
            lines.append(
                f"  eligible {i.get('old_eligible', '-')} -> {i['new_eligible']}, default rate "
                f"{_pct(i.get('old_default_rate'))} -> {_pct(i['new_default_rate'])} "
                f"({i.get('delta_pp', 0):+.2f} pp); label flips on common loans: {i.get('flips', '-')}"
            )
            lines.append(f"  new exclusions: {i['new_exclusions']}")
        lines.append(self.estimate.render())
        if self.version != self.active:
            lines.append(
                "NOTE: nothing is auto-promoted. The current serving model keeps serving until a champion "
                "for the new definition passes the harness gate and human approval."
            )
        return "\n".join(lines)


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.2f}%"


def _ctx(defn: DefaultDefinition, activate: bool, run_cycle: bool, log: Callable[[str], None]) -> PipelineContext:
    st = get_store("harness")
    return PipelineContext(
        version=definition_version(defn),
        definition=defn,
        activate=activate,
        run_cycle=run_cycle,
        previous_version=registry.active_version(st),
        log=log,
        store=st,
    )


def label_impact(new: DefaultDefinition, old: DefaultDefinition | None) -> dict:
    st = get_store("harness")
    if not st.table_exists("raw", "performance"):
        return {}
    perf = st.query(f"SELECT * FROM {st.fq('raw', 'performance')}")
    loans = st.query(
        f"SELECT loan_id, application_id, origination_month, decision_ts "
        f"FROM {st.fq('raw', 'applications_raw')} WHERE approved"
    )
    as_of = st.query(f"SELECT as_of_month FROM {st.fq('ops', 'data_version')} ORDER BY created_at DESC LIMIT 1")
    as_of_m = str(as_of["as_of_month"].iloc[0])
    new_l = build_labels(perf, loans, new, as_of_m)
    ns = label_summary(new_l)
    out = {"new_eligible": ns["n_eligible"], "new_default_rate": ns["default_rate"], "new_exclusions": ns["exclusions"]}
    if old is not None:
        old_l = build_labels(perf, loans, old, as_of_m)  # recomputed in memory, not read from storage
        os_ = label_summary(old_l)
        both = new_l.merge(old_l, on="loan_id", suffixes=("_n", "_o"))
        both = both[both["label_n"].notna() & both["label_o"].notna()]
        out.update(
            {
                "old_eligible": os_["n_eligible"],
                "old_default_rate": os_["default_rate"],
                "delta_pp": 100 * (ns["default_rate"] - os_["default_rate"]),
                "flips": int((both["label_n"] != both["label_o"]).sum()),
            }
        )
    return out


def plan(path: Path = DEFINITION_PATH, with_impact: bool = True, log: Callable[[str], None] = print) -> DefinitionPlan:
    defn = load_definition(path)
    st = get_store("harness")
    active = registry.active_version(st)
    old = registry.get_definition(st, active) if active else None
    ctx = _ctx(defn, True, False, log)
    pipe = build_pipeline()
    plans = pipe.plan(ctx, read_state(st))
    stale = [p.name for p in plans if p.status == "stale"]
    est = cost.estimate_stages(stale, include_agents="improvement_cycle" in stale)
    impact = label_impact(defn, old) if (with_impact and ctx.version != active) else {}
    return DefinitionPlan(
        ctx.version,
        active,
        registry.diff_definitions(old, defn),
        [(p.name, p.status, p.reason) for p in plans],
        est,
        impact,
    )


class ApprovalRequiredError(RuntimeError):
    pass


def apply(
    path: Path = DEFINITION_PATH,
    confirm: Callable[[str], bool] | None = None,
    approval_id: str | None = None,
    run_cycle: bool = True,
    log: Callable[[str], None] = print,
) -> dict:
    """Apply the YAML definition. Needs interactive confirmation OR a recorded approval for this exact hash."""
    p = plan(path, log=log)
    if p.is_noop:
        log("No changes: definition unchanged and all stages fresh. Nothing to do.")
        return {"version": p.version, "ran": [], "noop": True}
    st = get_store("harness")
    defn = load_definition(path)
    text = p.render()
    if approval_id is None:
        found = registry.find_approval(st, p.version)
        if confirm is None:
            if not found:
                raise ApprovalRequiredError(
                    f"no recorded approval for {p.version}; run `lau default-definition plan --approve` interactively"
                )
            approval_id = found
        else:
            log(text)
            if not confirm(f"Apply definition {p.version} and rebuild {len(p.stale)} stage(s)?"):
                log("Aborted by user.")
                return {"version": p.version, "ran": [], "aborted": True}
            approval_id = registry.record_approval(st, p.version, text)
    if p.stale:
        est = cost.estimate_stages(p.stale, include_agents=run_cycle and "improvement_cycle" in p.stale)
        cost.check_monthly_cap(est.total_usd)

    user = getpass.getuser()
    registry.register_version(st, defn, created_by=user)
    previous = registry.set_active(st, p.version, activated_by=user, approval_id=approval_id)
    if previous and previous != p.version:
        from lau.promotion.promote import mark_superseded

        n = mark_superseded(new_version=p.version)
        log(f"marked {n} champion(s) of other definitions as superseded_by_definition_change (kept, not deleted)")

    ctx = _ctx(defn, True, run_cycle, log)
    ctx.previous_version = previous if previous != p.version else None
    res = build_pipeline().run(ctx, lambda: read_state(st), lambda row: write_state(st, row))
    if previous != p.version:
        # Activation changed but some stages were already fresh (e.g. re-activating an older definition):
        # agent-facing views must still point at the newly active version, and the loop must restart.
        from lau.data.splits import read_split_meta
        from lau.pipeline.stages import refresh_active_views, stage_improvement_cycle

        if "splits" not in res.ran:
            refresh_active_views(st, p.version, read_split_meta(st, p.version)["oot_start"])
            log(f"active views re-pointed to {p.version}")
        if "improvement_cycle" not in res.ran:
            res.details["improvement_cycle"] = stage_improvement_cycle(ctx)
    dbu, usd = cost.metered_warehouse_usd()
    if usd:
        cost.log_cost("databricks_metered", usd, dbu=dbu, details=f"definition apply {p.version}")
    return {
        "version": p.version,
        "previous": previous,
        "ran": res.ran,
        "skipped": res.skipped,
        "details": res.details,
        "approval_id": approval_id,
    }


def build_side_by_side(path: Path, log: Callable[[str], None] = print) -> str:
    """Build labels/splits/catalog/baseline for another definition WITHOUT activating it."""
    defn = load_definition(path)
    st = get_store("harness")
    registry.register_version(st, defn, created_by=getpass.getuser())
    ctx = _ctx(defn, activate=False, run_cycle=False, log=log)
    only = {"labels", "splits", "catalog", "feature_registry_eval", "baseline_retrain", "harness_reference"}
    build_pipeline().run(ctx, lambda: read_state(st), lambda row: write_state(st, row), only=only)
    return ctx.version


def compare(other_path: Path, base_path: Path = DEFINITION_PATH, log: Callable[[str], None] = print) -> Path:
    """Side-by-side comparison of two definitions: label rates, model performance, feature importance."""
    from lau.definition import labels_io
    from lau.harness import metrics
    from lau.modeling import registry_io

    st = get_store("harness")
    versions = {}
    for label, pth in (("A", base_path), ("B", other_path)):
        d = load_definition(pth)
        v = definition_version(d)
        if v != registry.active_version(st):
            build_side_by_side(pth, log)
        versions[label] = (v, d)
    rows, fi = [], {}
    for label, (v, d) in versions.items():
        ls = json.loads(
            st.query(f"SELECT summary_json FROM {st.fq('ops', 'label_stats')} WHERE definition_version = '{v}'")[
                "summary_json"
            ].iloc[0]
        )
        bl = json.loads(
            st.query(f"SELECT details_json FROM {st.fq('ops', 'baselines')} WHERE definition_version = '{v}'")[
                "details_json"
            ].iloc[0]
        )
        model = registry_io.load_pd_model(registry_io.candidate_uri(bl["baseline_model_version"]), "harness")
        lab = labels_io.read_labels(st, v, "compare", splits=("validation",), allow_inactive=True)
        apps = st.query(f"SELECT * FROM {st.fq('curated', 'applications')} WHERE approved")
        val = apps.merge(lab[["application_id", "label"]], on="application_id")
        m = metrics.summary(val["label"].to_numpy(), model.predict_pd(val))
        rows.append(
            {
                "definition": label,
                "version": v,
                "name": d.metadata.name,
                "dpd": d.delinquency_threshold_dpd,
                "window": d.observation_window_months,
                "eligible": ls["n_eligible"],
                "default_rate": ls["default_rate"],
                "baseline_val_auc": m["auc"],
                "baseline_val_ks": m["ks"],
                "baseline_val_ece": m["ece"],
            }
        )
        fi[label] = model.feature_importance()
    df = pd.DataFrame(rows)
    fi_df = pd.DataFrame(fi).fillna(0).sort_values("A", ascending=False).head(20)
    out = get_settings().reports_dir.parent / f"compare_{short(versions['A'][0])}_{short(versions['B'][0])}.md"
    out.write_text(
        f"# Definition comparison ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)\n\n"
        "Each model is trained and evaluated on its OWN definition's labels and time splits; metrics are not a "
        "champion-vs-challenger comparison across definitions.\n\n## Label rates and baseline performance\n\n"
        + df.to_markdown(index=False, floatfmt=".4f")
        + "\n\n## Baseline feature importance (share)\n\n"
        + fi_df.to_markdown(floatfmt=".4f")
        + "\n"
    )
    return out
