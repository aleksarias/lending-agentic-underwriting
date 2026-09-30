"""Secrets, masking, SQL guard, agent isolation, grants spec."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd
import pytest

from lau.redact import SECRET_PATTERNS, redact, redact_text

ROOT = Path(__file__).resolve().parents[2]


def _repo_files() -> list[Path]:
    """Tracked + untracked-but-not-ignored files (what could be committed)."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [ROOT / p for p in out if (ROOT / p).is_file()]


def test_no_token_like_strings_in_committable_files():
    offenders = []
    for f in _repo_files():
        if f.suffix in {".png", ".jpg", ".parquet", ".db", ".lock"}:
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for pat in SECRET_PATTERNS[:5]:  # concrete credential formats (not the generic key=value heuristic)
            if pat.search(text):
                offenders.append((str(f.relative_to(ROOT)), pat.pattern))
    assert not offenders, offenders


def test_env_file_is_ignored_and_never_committable():
    committable = {str(p.relative_to(ROOT)) for p in _repo_files()}
    assert ".env" not in committable
    r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT)
    assert r.returncode == 0
    assert (ROOT / ".env.example").exists()


def test_redaction():
    fake_pat = "dapi" + "0123456789abcdef" * 2
    fake_ant = "sk-ant-" + "x" * 30
    s = f"token={fake_pat} and key {fake_ant}"
    assert fake_pat not in redact_text(s) and fake_ant not in redact_text(s)
    assert redact({"client_secret": "abc", "nested": [{"password": "p"}]}) == {
        "client_secret": "[REDACTED]",
        "nested": [{"password": "[REDACTED]"}],
    }


def test_masking_off_in_dev_on_in_prod(monkeypatch):
    from lau.masking import HashingMasker, IdentityMasker, build_masker
    from lau.settings import get_settings

    cfg = get_settings().masking
    assert isinstance(build_masker(cfg, enabled=False), IdentityMasker)
    get_settings.cache_clear()
    monkeypatch.setenv("LAU_ENVIRONMENT", "prod")
    try:
        s = get_settings()
        assert s.masking_enabled is True
        m = build_masker(s.masking, s.masking_enabled)
        assert isinstance(m, HashingMasker)
        df = pd.DataFrame(
            {"email": ["a.b@example.com"], "ssn": ["912-34-5678"], "note": ["call 555-123-4567"], "dti": [0.3]}
        )
        out = m.mask_frame(df)
        assert out["email"].iloc[0].startswith("h_") and out["ssn"].iloc[0].startswith("h_")
        assert "555-123-4567" not in out["note"].iloc[0]
        assert out["dti"].iloc[0] == 0.3
        assert m.mask_frame(df)["email"].iloc[0] == out["email"].iloc[0]  # deterministic (joins still work)
    finally:
        monkeypatch.delenv("LAU_ENVIRONMENT")
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM lending_uw_dev.experiments.reports",
        "SELECT 1; DROP TABLE lending_uw_dev.experiments.reports",
        "SELECT * FROM lending_uw_dev.holdout.oot_labels",
        "SELECT * FROM applications_dev",
        "SELECT * FROM system.billing.usage",
        "CREATE TABLE lending_uw_dev.experiments.x AS SELECT 1",
    ],
)
def test_agent_sql_guard_rejects(lake, sql):
    from lau.agents.tools.common import readonly_sql
    from lau.store import AccessDeniedError

    with pytest.raises(AccessDeniedError):
        readonly_sql(sql)


def test_agent_sql_guard_caps_rows(lake):
    from lau.agents.tools.common import MAX_SQL_ROWS, readonly_sql
    from lau.settings import get_settings

    df = readonly_sql(f"SELECT * FROM {get_settings().fq('curated', 'applications_dev')}")
    assert len(df) == MAX_SQL_ROWS


def test_agent_options_are_locked_down(lake):
    from lau.agents.runner import BUILTIN_TOOLS, CycleContext, build_options
    from lau.agents.tools import role_tools as rt
    from lau.trace import TraceWriter

    ctx = CycleContext("cy-test", lake["version"], TraceWriter("cy-test", lake["version"]))
    for role, tools in [
        ("modeling", rt.modeling_tools(ctx)),
        ("redteam", rt.redteam_tools(ctx)),
        ("curator", rt.curator_tools(ctx)),
    ]:
        o = build_options(role, tools, ctx)
        assert o.tools == []
        assert o.permission_mode == "dontAsk"
        assert o.setting_sources == []
        assert all(t.startswith(f"mcp__lau_{role}__") for t in o.allowed_tools)
        assert set(BUILTIN_TOOLS) <= set(o.disallowed_tools)
        assert list(o.mcp_servers) == [f"lau_{role}"]
        assert o.env["DATABRICKS_CONFIG_FILE"] == "/dev/null"
        assert all(v == "" for k, v in o.env.items() if k.startswith(("DATABRICKS_TOKEN", "LAU_")))
        assert o.max_budget_usd <= ctx.budgets["agents"][role]["max_budget_usd"]
        assert not list(Path(o.cwd).iterdir())  # empty sandbox dir
    names = {t.name for t in rt.modeling_tools(ctx)}
    assert not names & {"promote", "approve", "apply_definition", "write_file", "execute_sql"}


def test_no_agent_tool_can_touch_definition_or_production():
    """Static: agent tool modules never reference the definition YAML, approvals or production writes."""
    tool_src = "".join(p.read_text() for p in (ROOT / "src/lau/agents/tools").glob("*.py"))
    for forbidden in (
        "default_definition.yaml",
        "definition_ops",
        "record_approval",
        "promote(",
        "'production'",
        "set_active(",
    ):
        assert forbidden not in tool_src, forbidden


def test_grants_spec():
    from lau.governance.grants import can_read, can_write

    assert not can_read("agent", "holdout", "oot_labels")
    assert not can_read("promoter", "holdout", "oot_labels")
    assert can_read("harness", "holdout", "oot_labels")
    assert can_read("agent", "labels", "labels_active") and not can_read("agent", "labels", "labels_all")
    assert not can_write("agent", "production", "pd_model") and not can_write("harness", "production", "x")
    assert can_write("promoter", "production", "promotions")
    assert can_write("agent", "experiments", "reports") and not can_write("agent", "ops", "agent_trace")
