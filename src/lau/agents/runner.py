"""Agent runtime: one narrowly-scoped Claude Agent SDK session per specialist run.

Isolation per run:
  * tools=[]                 -> no built-in tools at all (no Bash/Read/Write/Edit/Web*/Task)
  * allowed_tools            -> only this role's in-process MCP tools (mcp__lau_<role>__<tool>)
  * disallowed_tools         -> built-ins listed explicitly as belt-and-braces
  * permission_mode dontAsk  -> anything not pre-approved is denied, never prompted
  * can_use_tool + PreToolUse hook re-check the allow-list and trace every call
  * env                      -> DATABRICKS_*/LAU_*/cloud creds blanked; only ANTHROPIC_API_KEY passed
  * cwd                      -> an empty temp dir; setting_sources=[] (no CLAUDE.md / settings / skills)
  * max_turns, max_budget_usd, wall-clock timeout -> hard caps; spend is charged to the cycle budget
Agent tools execute in THIS process using the agent-role Store (UC grants + in-process ACL).
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

from lau.cost import BudgetExceededError
from lau.credentials import agent_subprocess_env
from lau.masking import get_masker
from lau.redact import redact_text
from lau.settings import get_settings
from lau.trace import TraceWriter

BUILTIN_TOOLS = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Task",
    "Agent",
    "NotebookEdit",
    "TodoWrite",
    "Skill",
    "BashOutput",
    "KillShell",
]
MAX_TOOL_RESULT_CHARS = 20000
PROMPTS_DIR = __import__("pathlib").Path(__file__).parent / "prompts"


class AgentRunError(RuntimeError):
    """The model API failed (auth, quota, overload): the run produced no work and must not count as success."""


@dataclass
class CycleContext:
    cycle_id: str
    version: str
    trace: TraceWriter
    started: float = field(default_factory=time.time)
    spent_usd: float = 0.0
    experiments_used: int = 0
    features_proposed: int = 0
    per_agent: dict[str, dict] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)  # artifacts passed between agents (ids, not chat)

    @property
    def budgets(self) -> dict:
        return get_settings().budgets

    def remaining_usd(self) -> float:
        return self.budgets["cycle"]["max_anthropic_usd"] - self.spent_usd

    def remaining_seconds(self) -> float:
        return self.budgets["cycle"]["max_wall_clock_min"] * 60 - (time.time() - self.started)


@dataclass
class AgentRunResult:
    role: str
    text: str
    cost_usd: float
    num_turns: int
    is_error: bool
    subtype: str
    tool_calls: list[str]
    duration_s: float


def tool_text(payload: Any) -> dict:
    """Standard tool result: masked + redacted + truncated JSON/text."""
    masker = get_masker()
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str, indent=1)
    text = redact_text(masker.mask_text(text))
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + f"\n...[truncated {len(text) - MAX_TOOL_RESULT_CHARS} chars]"
    return {"content": [{"type": "text", "text": text}]}


def tool_error(msg: str) -> dict:
    return {"content": [{"type": "text", "text": f"ERROR: {redact_text(msg)[:4000]}"}], "is_error": True}


# Roles that are not cycle specialists (the console's read-only question answering): their prompt is used without
# the shared cycle preamble in _common.md.
STANDALONE_ROLES = frozenset({"ask"})


def load_prompt(role: str, **fmt: str) -> str:
    body = (PROMPTS_DIR / f"{role}.md").read_text()
    text = body if role in STANDALONE_ROLES else (PROMPTS_DIR / "_common.md").read_text() + "\n\n" + body
    for k, v in fmt.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def build_options(role: str, tools: list, ctx: CycleContext):
    """ClaudeAgentOptions for one specialist run (pure; unit-tested for isolation properties)."""
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        HookMatcher,
        PermissionResultAllow,
        PermissionResultDeny,
        create_sdk_mcp_server,
    )

    s = get_settings()
    caps = s.budgets["agents"][role]
    server_name = f"lau_{role}"
    allowed = [f"mcp__{server_name}__{t.name}" for t in tools]
    allowed_set = set(allowed)

    async def guard(tool_name: str, tool_input: dict, _ctx) -> Any:
        if tool_name in allowed_set:
            return PermissionResultAllow()
        ctx.trace.log(
            role, "denied_tool", {"tool": tool_name, "input": tool_input}, None, state_changing=False, status="denied"
        )
        return PermissionResultDeny(message=f"{tool_name} is not permitted for the {role} agent")

    async def pre_hook(hook_input: dict, tool_use_id: str | None, _hctx) -> dict:
        if hook_input.get("tool_name", "") not in allowed_set:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "tool not in role allow-list",
                }
            }
        return {}

    return ClaudeAgentOptions(
        system_prompt=load_prompt(role, definition_version=ctx.version, cycle_id=ctx.cycle_id),
        model=s.models["agents"][role],
        tools=[],
        allowed_tools=allowed,
        disallowed_tools=BUILTIN_TOOLS,
        permission_mode="dontAsk",
        can_use_tool=guard,
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_hook])]},
        mcp_servers={server_name: create_sdk_mcp_server(name=server_name, tools=tools)},
        strict_mcp_config=True,
        max_turns=int(caps["max_turns"]),
        max_budget_usd=float(min(caps["max_budget_usd"], ctx.remaining_usd())),
        env=agent_subprocess_env(),
        cwd=tempfile.mkdtemp(prefix=f"lau_{role}_"),
        setting_sources=[],
        skills=[],
    )


async def run_agent(role: str, prompt: str, tools: list, ctx: CycleContext) -> AgentRunResult:
    from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, TextBlock, ToolUseBlock

    caps = get_settings().budgets["agents"][role]
    if ctx.remaining_usd() <= 0.05:
        raise BudgetExceededError(f"cycle Anthropic budget exhausted before {role}")
    if ctx.remaining_seconds() <= 30:
        raise BudgetExceededError(f"cycle wall-clock budget exhausted before {role}")
    options = build_options(role, tools, ctx)
    t0 = time.time()
    texts: list[str] = []
    calls: list[str] = []
    result: ResultMessage | None = None

    async def _session() -> None:
        nonlocal result
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            texts.append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            calls.append(block.name)
                elif isinstance(msg, ResultMessage):
                    result = msg

    timeout = min(caps["timeout_min"] * 60, ctx.remaining_seconds())
    timed_out = False
    try:
        await asyncio.wait_for(_session(), timeout=timeout)
    except TimeoutError:
        timed_out = True
    cost = float(result.total_cost_usd or 0.0) if result else 0.0
    ctx.spent_usd += cost
    out = AgentRunResult(
        role=role,
        text="\n".join(texts)[-8000:],
        cost_usd=cost,
        num_turns=result.num_turns if result else 0,
        is_error=bool(result.is_error) if result else True,
        subtype="timeout" if timed_out else (result.subtype if result else "no_result"),
        tool_calls=calls,
        duration_s=time.time() - t0,
    )
    api_error = out.text.lstrip().startswith("API Error") or (result is not None and result.is_error)
    if api_error and out.subtype == "success":
        out.subtype = "api_error"
        out.is_error = True
    ctx.per_agent.setdefault(role, {"runs": 0, "cost_usd": 0.0, "turns": 0})
    ctx.per_agent[role]["runs"] += 1
    ctx.per_agent[role]["cost_usd"] += cost
    ctx.per_agent[role]["turns"] += out.num_turns
    ctx.trace.log(
        role,
        "agent_run",
        {"prompt": prompt[:2000], "model": options.model},
        {"subtype": out.subtype, "turns": out.num_turns, "tool_calls": calls, "final_text": out.text[-1500:]},
        principal="agent",
        state_changing=False,
        cost_usd=cost,
        status="ok" if not out.is_error else out.subtype,
    )
    if out.subtype in ("api_error", "no_result"):
        raise AgentRunError(f"{role}: {out.text[-500:] or out.subtype}")
    return out
