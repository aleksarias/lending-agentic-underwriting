"""People's direct input to the loop: rejected features are enforced by the harness; pinned hypotheses reach the
planner; both live where agents cannot write."""

from __future__ import annotations

import pytest


def test_a_rejected_feature_fails_validation_until_restored(lake):
    from lau.data.features import load_dev_frame
    from lau.governance import human_input
    from lau.harness.evaluate import evaluate_model
    from lau.modeling.model import PDModel
    from lau.modeling.search_space import defaults
    from lau.store import get_store

    st = get_store("harness")
    v = lake["version"]
    dev = load_dev_frame(st, v, "test")
    tr = dev[dev["split"] == "train"]
    m = PDModel("logreg", defaults("logreg"), ["bureau_score", "dti", "pmt_to_income"], [], v).fit(
        tr, tr["label"].to_numpy()
    )
    with pytest.raises(ValueError):
        human_input.feature_decision("dti", "reject", "short", "alice")  # a reason is required
    human_input.feature_decision("dti", "reject", "uses stale bureau pulls", "alice")
    try:
        ev = evaluate_model(m, v, "test:rejected", count_test=False)
        assert ev["checks"]["no_rejected_features"] is False and ev["rejected_features_used"] == ["dti"]
        assert not ev["passed_validation"]
    finally:
        human_input.feature_decision("dti", "restore", "re-checked the source", "alice")
    ev = evaluate_model(m, v, "test:restored", count_test=False)
    assert ev["checks"]["no_rejected_features"] is True


def test_pinned_hypotheses_and_rejections_reach_the_planner_not_the_agent_store(lake):
    from lau.governance import human_input
    from lau.store import AccessDeniedError, get_store

    h = human_input.pin("thin files: income volatility matters more", "alice")
    try:
        assert h["hypothesis_id"] in {x["hypothesis_id"] for x in human_input.pinned()}
        agent = get_store("agent")
        with pytest.raises(AccessDeniedError):
            agent.query(f"SELECT * FROM {agent.fq('ops', 'pinned_hypotheses')}")
    finally:
        human_input.unpin(h["hypothesis_id"], "alice")
    assert h["hypothesis_id"] not in {x["hypothesis_id"] for x in human_input.pinned()}
    with pytest.raises(ValueError):
        human_input.unpin(h["hypothesis_id"], "alice")
