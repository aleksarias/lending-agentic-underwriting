"""End-to-end demo on synthetic data (Databricks backend by default).

Run by a HUMAN (it edits config/default_definition.yaml and applies it with your confirmation flags):
  1. ensure 90 DPD is active and built; run an improvement cycle
  2. switch the definition file to 60 DPD (backup kept), plan, apply -> full invalidation + rebuild
  3. run a fresh cycle under 60 DPD
  4. side-by-side comparison + a markdown report of what changed
Promotion is NOT automated: the report lists the `lau promote <mv>` command for your approval.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lau.agents.orchestrator import run_cycle_sync  # noqa: E402
from lau.definition.registry import active_version  # noqa: E402
from lau.modeling import registry_io  # noqa: E402
from lau.pipeline import definition_ops as ops  # noqa: E402
from lau.store import get_store  # noqa: E402

CFG = ROOT / "config" / "default_definition.yaml"
D90 = ROOT / "config" / "definitions" / "dpd90_ever_12m.yaml"
D60 = ROOT / "config" / "definitions" / "dpd60_ever_12m.yaml"


def _stats(version: str) -> dict:
    st = get_store("harness")
    ls = json.loads(
        st.query(f"SELECT summary_json FROM {st.fq('ops', 'label_stats')} WHERE definition_version = '{version}'")[
            "summary_json"
        ].iloc[0]
    )
    ref = (
        st.query(
            f"SELECT val_auc, val_ks, val_ece, baseline_model_version FROM {st.fq('ops', 'harness_reference')} "
            f"WHERE definition_version = '{version}'"
        )
        .iloc[0]
        .to_dict()
    )
    return {"labels": ls, "reference": ref}


def main() -> None:
    log = print
    out = ROOT / "reports" / f"demo_{datetime.now(UTC):%Y%m%d%H%M}.md"
    lines = [f"# Demo: 90 DPD → 60 DPD ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)", ""]

    # 1. 90 DPD
    shutil.copy(D90, CFG)
    r90 = ops.apply(CFG, confirm=lambda q: True, run_cycle=False, log=log)
    v90 = active_version(get_store("harness"))
    c90 = run_cycle_sync("demo: 90 DPD", log)
    s90 = _stats(v90)

    # 2. change to 60 DPD
    backup = CFG.with_suffix(".yaml.bak")
    shutil.copy(CFG, backup)
    shutil.copy(D60, CFG)
    plan = ops.plan(CFG, log=log)
    log(plan.render())
    r60 = ops.apply(CFG, confirm=lambda q: True, run_cycle=False, log=log)
    v60 = active_version(get_store("harness"))
    c60 = run_cycle_sync("demo: definition change to 60 DPD", log)
    s60 = _stats(v60)
    cmp = ops.compare(D90, base_path=CFG, log=log)
    serving = registry_io.serving_model("harness")

    lines += [
        "## Definition change plan (as shown to the human)",
        "```",
        plan.render(),
        "```",
        "## What was rebuilt",
        f"- 90 DPD `{v90}`: ran {r90.get('ran')}",
        f"- 60 DPD `{v60}`: ran {r60['ran']}",
        "## Label and reference changes",
        "| | 90 DPD | 60 DPD |",
        "|---|---|---|",
        f"| eligible loans | {s90['labels']['n_eligible']} | {s60['labels']['n_eligible']} |",
        f"| default rate | {s90['labels']['default_rate']:.2%} | {s60['labels']['default_rate']:.2%} |",
        f"| baseline val AUC | {s90['reference']['val_auc']:.4f} | {s60['reference']['val_auc']:.4f} |",
        f"| baseline val ECE | {s90['reference']['val_ece']:.4f} | {s60['reference']['val_ece']:.4f} |",
        "",
        "## Improvement cycles",
        f"- 90 DPD cycle `{c90['cycle_id']}`: status {c90['status']}, challenger {c90.get('challenger')}, "
        f"passed validation {c90.get('challenger_passed_validation')}, red team {c90.get('redteam_verdict')}, "
        f"compliance {c90.get('compliance_verdict')}, ${c90['anthropic_usd']:.2f}",
        f"- 60 DPD cycle `{c60['cycle_id']}`: status {c60['status']}, challenger {c60.get('challenger')}, "
        f"passed validation {c60.get('challenger_passed_validation')}, red team {c60.get('redteam_verdict')}, "
        f"compliance {c60.get('compliance_verdict')}, ${c60['anthropic_usd']:.2f}",
        "",
        "## Serving model",
        f"- {serving or 'none promoted (legacy policy); promotion needs `lau promote <mv>` + approval'}",
        "",
        "## Side-by-side comparison",
        cmp.read_text(),
        "",
        f"_Backup of the previous definition file: `{backup.name}`._",
    ]
    out.write_text("\n".join(lines) + "\n")
    log(f"demo report: {out}")


if __name__ == "__main__":
    main()
