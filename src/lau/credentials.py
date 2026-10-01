"""All credentials come from `.env` (gitignored, mode 600). Nothing else in the repo holds a secret.

Design rules:
  * `.env` is parsed into a private dict. It is NOT loaded into os.environ, so child processes (notably the
    Claude Code CLI spawned by the Agent SDK) never inherit Databricks credentials.
  * Each role gets its own explicit databricks-sdk `Config`. Agent tools only ever receive the agent Config.
  * Real process env vars override `.env` (for CI/jobs), with the same variable names.
  * Values are never printed or logged; see lau.redact for trace redaction.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

from dotenv import dotenv_values

from lau.settings import ROOT

ENV_FILE = Path(os.environ.get("LAU_ENV_FILE", ROOT / ".env"))

# Anything matching these must never reach an agent subprocess.
_SENSITIVE_ENV_PREFIXES = ("DATABRICKS_", "LAU_", "AWS_", "AZURE_", "GOOGLE_", "ARM_")


class CredentialsMissingError(RuntimeError):
    pass


def _values() -> dict[str, str]:
    vals: dict[str, str] = {}
    if ENV_FILE.exists():
        vals.update({k: v for k, v in dotenv_values(ENV_FILE).items() if v})
    for k, v in os.environ.items():
        if v and (k.startswith(("DATABRICKS_", "LAU_")) or k in ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID")):
            vals[k] = v
    return vals


def host() -> str:
    from lau.settings import get_settings

    return _values().get("DATABRICKS_HOST") or get_settings().project.host


def databricks_config(role: str):
    """databricks-sdk Config for a role. Raises CredentialsMissingError with an actionable message."""
    from databricks.sdk.core import Config

    vals = _values()
    if os.environ.get("LAU_RUNTIME_ROLE") == role:
        return Config()  # inside a Databricks job: the job's run_as identity, native auth
    if role == "admin":
        profile = vals.get("DATABRICKS_CONFIG_PROFILE")
        if profile:  # OAuth (U2M) through the Databricks CLI's token cache: preferred over a PAT
            return Config(profile=profile, host=host())
        if vals.get("DATABRICKS_TOKEN"):
            return Config(host=host(), token=vals["DATABRICKS_TOKEN"], auth_type="pat")
        raise CredentialsMissingError(
            "Admin Databricks credentials missing. In .env set DATABRICKS_CONFIG_PROFILE (after "
            "`databricks auth login --host <host> --profile <name>`) or DATABRICKS_TOKEN."
        )
    cid = vals.get(f"LAU_{role.upper()}_CLIENT_ID")
    csec = vals.get(f"LAU_{role.upper()}_CLIENT_SECRET")
    if not (cid and csec):
        raise CredentialsMissingError(
            f"Service principal credentials for role '{role}' missing. Set LAU_{role.upper()}_CLIENT_ID and "
            f"LAU_{role.upper()}_CLIENT_SECRET in .env (run `lau init` to create them)."
        )
    return Config(host=host(), client_id=cid, client_secret=csec, auth_type="oauth-m2m")


def has_role_credentials(role: str) -> bool:
    try:
        databricks_config(role)
        return True
    except CredentialsMissingError:
        return False


def anthropic_key() -> str:
    key = _values().get("ANTHROPIC_API_KEY")
    if not key:
        raise CredentialsMissingError("ANTHROPIC_API_KEY missing: set it in .env.")
    return key


def has_anthropic_key() -> bool:
    return bool(_values().get("ANTHROPIC_API_KEY"))


def agent_subprocess_env() -> dict[str, str]:
    """Env overrides for the Claude Code CLI subprocess.

    The SDK merges os.environ with these overrides, so every sensitive key present in os.environ is blanked,
    and the only credential passed is the Anthropic key.
    """
    env = {k: "" for k in os.environ if k.startswith(_SENSITIVE_ENV_PREFIXES)}
    env["ANTHROPIC_API_KEY"] = anthropic_key()
    ws = _values().get("ANTHROPIC_WORKSPACE_ID")
    if ws:  # org keys not scoped to a workspace must name one on every request
        env["ANTHROPIC_CUSTOM_HEADERS"] = f"anthropic-workspace-id: {ws}"
    env["DATABRICKS_CONFIG_FILE"] = "/dev/null"  # even if a Read tool existed, no profile could be loaded
    return env


def write_env_values(updates: dict[str, str]) -> None:
    """Upsert keys in .env (keeps comments/order, mode 600). Used by `lau init` for SP credentials."""
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    old_umask = os.umask(0o077)
    try:
        ENV_FILE.write_text("\n".join(out) + "\n")
    finally:
        os.umask(old_umask)
    ENV_FILE.chmod(0o600)


def _forget_mlflow_clients() -> None:
    """MLflow caches its Databricks client by host, token and profile, not by the credentials in the environment, so
    without this the first identity used in a process would silently serve every later role (e.g. harness writes
    landing under the promoter's name, or a promoter write denied as the harness)."""
    try:
        from mlflow.utils.rest_utils import get_workspace_client

        get_workspace_client.cache_clear()
    except Exception:  # noqa: BLE001, S110 - an MLflow version without this cache needs nothing
        pass


@contextlib.contextmanager
def role_env(role: str) -> Iterator[None]:
    """Temporarily expose ONE role's Databricks credentials via env vars (for MLflow, which reads env).

    Used only around MLflow calls in the orchestrating Python process; restored afterwards. Agent subprocesses
    are spawned with `agent_subprocess_env()` which blanks these keys regardless.
    """
    if os.environ.get("LAU_RUNTIME_ROLE") == role:
        yield  # inside a Databricks job as this identity: MLflow picks up the job's native credentials
        return
    cfg = databricks_config(role)
    keys = [
        "DATABRICKS_HOST",
        "DATABRICKS_TOKEN",
        "DATABRICKS_CLIENT_ID",
        "DATABRICKS_CLIENT_SECRET",
        "DATABRICKS_CONFIG_PROFILE",
        "DATABRICKS_AUTH_TYPE",
    ]
    saved = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ.pop(k, None)
        os.environ["DATABRICKS_HOST"] = cfg.host
        if role == "admin":
            if cfg.token:
                os.environ["DATABRICKS_TOKEN"] = cfg.token
            else:
                os.environ["DATABRICKS_CONFIG_PROFILE"] = cfg.profile
        else:
            os.environ["DATABRICKS_CLIENT_ID"] = cfg.client_id
            os.environ["DATABRICKS_CLIENT_SECRET"] = cfg.client_secret
        _forget_mlflow_clients()  # MLflow must build its client from THIS role's credentials
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _forget_mlflow_clients()
