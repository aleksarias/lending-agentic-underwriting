"""What-if for the credit policy: what a different PD cut-off would do, on the active definition's validation window.

For each candidate cut-off, from the serving champion's PD (or the reference baseline when nothing serves):
  approval_rate      share of ALL applications in the window (through the door) at or below the cut-off
  expected_bad_rate  mean PD of those approvals (what the model expects)
  known_bad_rate     realized default rate of approvals that have an outcome: loans the legacy policy funded. The
                     legacy policy declined the rest, so this is biased towards better applicants (no reject inference)
The active policy's approve and refer cut-offs are marked. Evidence step `policy_tradeoff` -> ops.policy_tradeoff.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CUTOFFS = [round(x, 3) for x in np.arange(0.02, 0.305, 0.01)]


def _model(ctx):
    from lau.modeling import registry_io

    serving = registry_io.serving_model("harness")
    if serving:
        uri = f"models:/{registry_io.production_model_name()}/{serving['model_version']}"
        return registry_io.load_pd_model(uri, "harness"), f"production v{serving['model_version']}"
    ref = ctx.store.query(
        f"SELECT baseline_model_version FROM {ctx.store.fq('ops', 'harness_reference')} "
        f"WHERE definition_version = '{ctx.active_version}'"
    )
    if ref.empty:
        return None, None
    mv = str(ref["baseline_model_version"].iloc[0])
    return registry_io.load_pd_model(registry_io.candidate_uri(mv), "harness"), f"baseline v{mv}"


def compute(ctx) -> pd.DataFrame:
    from lau.decision import policy as policies
    from lau.definition.labels_io import read_labels
    from lau.evidence.context import EvidenceNotReadyError

    model, label = _model(ctx)
    if model is None:
        raise EvidenceNotReadyError("no serving model and no reference baseline for the active definition")
    lo, hi = ctx.validation_range
    pop = ctx.all_apps[(ctx.all_apps["origination_month"] >= lo) & (ctx.all_apps["origination_month"] <= hi)]
    if pop.empty:
        raise EvidenceNotReadyError("no applications in the validation window")
    pd_all = np.asarray(model.predict_pd(pop), dtype=float)
    lab = read_labels(ctx.store, ctx.active_version, "policy_tradeoff", splits=("validation",))
    known = pop[["application_id"]].assign(pd=pd_all).merge(lab[["application_id", "label"]], on="application_id")
    found = None
    try:
        found = policies.active()
    except Exception:  # noqa: BLE001 - no policy tables yet: the curve is still useful
        found = None
    approve_at = found[1].decision.approve_max_pd if found else None
    refer_at = found[1].decision.refer_max_pd if found else None
    cutoffs = sorted(set(CUTOFFS) | {c for c in (approve_at, refer_at) if c is not None})
    rows = []
    for c in cutoffs:
        ok = pd_all <= c
        k = known[known["pd"] <= c]
        rows.append(
            {
                "cutoff": float(c),
                "approval_rate": float(ok.mean()),
                "expected_bad_rate": float(pd_all[ok].mean()) if ok.any() else None,
                "known_n": len(k),
                "known_bad_rate": float(k["label"].astype(float).mean()) if len(k) else None,
                "is_policy_approve": approve_at is not None and abs(c - approve_at) < 1e-9,
                "is_policy_refer": refer_at is not None and abs(c - refer_at) < 1e-9,
            }
        )
    out = pd.DataFrame(rows)
    out.insert(0, "n_applications", len(pop))
    out.insert(0, "window_end", hi)
    out.insert(0, "window_start", lo)
    out.insert(0, "model_label", label)
    out.insert(0, "definition_version", ctx.active_version)
    out.insert(0, "run_id", ctx.run_id)
    out.insert(0, "computed_at", ctx.computed_at)
    return out
