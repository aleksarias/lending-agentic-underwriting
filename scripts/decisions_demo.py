"""Local, synthetic walk-through of real-time decisioning (no Databricks, no endpoint, no Anthropic calls).

Builds a fresh small lake, then: approves and activates the policy (as "demo-reviewer", in this throwaway lake only),
registers two champions (one serving), builds the decision model, sends three simulated months of applications,
promotes the second champion into a shadow rollout, sends another month, runs the three release checks, then runs the
feedback loop for fourteen more months (servicer feed, ingestion, maturation) and the production evidence steps.

    uv run python scripts/decisions_demo.py --out .local_lake/decisions_demo
    LAU_ENV_FILE=/dev/null LAU_BACKEND=local LAU_LOCAL_LAKE=.local_lake/decisions_demo \
        LAU_CONFIG_DIR=.local_lake/decisions_demo/config uv run lau console
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".local_lake" / "decisions_demo"))
    ap.add_argument("--applications", type=int, default=12000)
    args = ap.parse_args()
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    cfg = out / "config"
    shutil.copytree(ROOT / "config", cfg)
    shutil.copy(ROOT / "config" / "definitions" / "dpd90_ever_12m.yaml", cfg / "default_definition.yaml")
    synth = yaml.safe_load((cfg / "synth.yaml").read_text())
    synth.update({"n_applications": args.applications, "n_noise_numeric": 20, "n_new_applications": 1000})
    (cfg / "synth.yaml").write_text(yaml.safe_dump(synth))
    decisioning = yaml.safe_load((cfg / "decisioning.yaml").read_text())
    decisioning["traffic"]["applications_per_month"] = 400
    decisioning["rollout"]["min_shadow_decisions"] = 200
    (cfg / "decisioning.yaml").write_text(yaml.safe_dump(decisioning, sort_keys=False))
    os.environ.update(
        {
            "LAU_BACKEND": "local",
            "LAU_ENVIRONMENT": "dev",
            "LAU_CONFIG_DIR": str(cfg),
            "LAU_LOCAL_LAKE": str(out),
            "LAU_STATE_DIR": str(out / "state"),
            "LAU_LESSONS_FILE": str(out / "LESSONS.md"),
            "LAU_REPORTS_DIR": str(out / "reports"),
            "LAU_ENV_FILE": "/dev/null",
            "MLFLOW_DISABLE_AGENT_HINT": "1",
        }
    )
    sys.path.insert(0, str(ROOT / "src"))
    run(cfg)
    print(f"\nlake ready: {out}")


def run(cfg: Path) -> None:
    import warnings

    warnings.filterwarnings("ignore")
    from lau.data.features import load_dev_frame
    from lau.decision import build, checks, policy, rollout, traffic
    from lau.definition.registry import active_version
    from lau.governance.uc_layout import run_init
    from lau.modeling import registry_io
    from lau.modeling.model import PDModel
    from lau.modeling.search_space import defaults
    from lau.pipeline import definition_ops as ops
    from lau.store import get_store
    from lau.synth.ingest import gen_data

    quiet = lambda m: None  # noqa: E731
    run_init(log=quiet)
    gen_data(log=quiet)
    ops.apply(path=cfg / "default_definition.yaml", confirm=lambda q: True, run_cycle=False, log=quiet)
    st = get_store("harness")
    version = active_version(st)
    dev = load_dev_frame(st, version, "demo")
    train = dev[dev["split"] == "train"]
    prod = registry_io.production_model_name()
    feats = {
        "a": ["bureau_score", "dti", "util_revolving", "inq_6m", "pmt_to_income", "num_delinq_24m"],
        "b": [
            "bureau_score",
            "dti",
            "util_revolving",
            "pmt_to_income",
            "num_delinq_24m",
            "cf_nsf_count_6m",
            "cf_income_cv_6m",
            "cf_min_balance_6m",
        ],
    }
    versions = {}
    for key, cols in feats.items():
        model = PDModel("lightgbm", defaults("lightgbm"), cols, [], version).fit(train, train["label"].to_numpy())
        _, mv = registry_io.log_candidate(model, {}, {"author": "decisions-demo"}, train, role="harness")
        with registry_io.mlflow_session("promoter") as c:
            try:
                c.create_registered_model(prod)
            except Exception:  # noqa: BLE001, S110 - exists
                pass
            pv = c.copy_model_version(registry_io.candidate_uri(mv), prod)
            for k, v in {"definition_version": version, "lau_kind": "champion", "status": "champion"}.items():
                c.set_model_version_tag(prod, pv.version, k, v)
            c.set_registered_model_alias(prod, registry_io.champion_alias(version), pv.version)
        versions[key] = str(pv.version)
    with registry_io.mlflow_session("promoter") as c:
        c.set_registered_model_alias(prod, registry_io.SERVING_ALIAS, versions["a"])
    print(f"champions: v{versions['a']} (serving), v{versions['b']}")

    p = policy.load_policy(cfg / "policy.yaml")
    policy.record_approval(p, "demo-reviewer", "local synthetic walk-through only")
    print("policy:", policy.apply(cfg / "policy.yaml", by="demo-reviewer"))
    build.build(log=print)
    traffic.originate(months=3, kind="inprocess", log=print)
    r = rollout.start(versions["b"], version, promotion_id=None, by="demo-reviewer")
    build.build(log=print)
    traffic.originate(months=1, kind="inprocess", log=print)
    print("shadow report:", rollout.report(r["rollout_id"]))
    checks.parity(n=200, log=print)
    checks.load(n=120, concurrency=4, kind="inprocess", log=print)
    checks.rollback(n=100, log=print)

    # the feedback loop: the servicer reports on booked loans each month; loans mature after the 12-month window
    from lau.feedback import feed, production, servicer

    servicer.run(log=print)
    feed.ingest(log=print)
    for _ in range(14):
        traffic.originate(months=1, kind="inprocess", log=quiet)
        servicer.run(log=quiet)
        feed.ingest(log=quiet)
        production.maturation_check(log=print)
    from lau.evidence.run import run_all

    run_all(
        log=print,
        only=["model_registry", "production_evidence", "decision_fairness", "serving_parity"],
    )  # the console reads the serving alias from the registry mirror, and the production evidence


if __name__ == "__main__":
    main()
