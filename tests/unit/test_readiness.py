"""Production readiness: evidence is gathered, sign-offs are recorded per named role, and nothing is 'ready' until
every required role signed. Signing needs a person at a terminal."""

from __future__ import annotations

import pytest


def test_checklist_is_open_until_every_role_signs(lake):
    from lau import readiness

    s = readiness.status()
    assert not s["ready"] and "does not claim compliance" in s["statement"]
    item = next(i for i in s["items"] if i["id"] == "parallel_run")
    assert item["state"] == "open" and [r["role"] for r in item["signoffs"]] == ["credit_policy"]
    with pytest.raises(ValueError, match="signed by"):
        readiness.record("parallel_run", "security", "alice", "sign", "reviewed the shadow report in full")
    with pytest.raises(ValueError, match="at least 20"):
        readiness.record("parallel_run", "credit_policy", "alice", "sign", "looks fine")
    readiness.record("parallel_run", "credit_policy", "alice", "sign", "reviewed the shadow report in full")
    assert next(i for i in readiness.status()["items"] if i["id"] == "parallel_run")["state"] == "signed"
    readiness.record("parallel_run", "credit_policy", "bob", "revoke", "the comparison window was too short")
    assert next(i for i in readiness.status()["items"] if i["id"] == "parallel_run")["state"] == "open"
    readiness.record("compliance", "counsel", "carol", "decline", "notice timing is not settled with servicing")
    assert next(i for i in readiness.status()["items"] if i["id"] == "compliance")["state"] == "declined"


def test_evidence_is_gathered_without_judgement(lake):
    from lau import readiness

    ev = readiness.evidence()
    assert set(ev) == {i["id"] for i in readiness.items()}
    real = {e["label"]: e["met"] for e in ev["real_data"]}
    assert real["Real data loaded"] is False and real["A production workspace is configured"] is False
    assert any(e["label"] == "Runbook written" and e["met"] for e in ev["security_operations"])


def test_signing_needs_a_person_at_a_terminal(lake):
    from typer.testing import CliRunner

    from lau.cli import app

    res = CliRunner().invoke(app, ["readiness", "sign", "real_data", "--role", "counsel", "--note", "x" * 30])
    assert res.exit_code == 1 and "interactive terminal" in res.output


def test_console_shows_readiness_from_stored_evidence(lake):
    from fastapi.testclient import TestClient

    from lau.console.app import create_app
    from lau.evidence.run import run_all

    run_all(log=lambda m: None, only="readiness_evidence")
    body = TestClient(create_app()).get("/api/readiness").json()
    assert {"items", "ready", "statement"} <= set(body) and not body["ready"]
    assert all(i["evidence"] for i in body["items"])
