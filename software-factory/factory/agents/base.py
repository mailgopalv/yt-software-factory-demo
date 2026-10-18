"""What every agent has in common, and how one agent run is executed with the Claude Agent SDK."""
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    HookMatcher,
    RateLimitEvent,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from factory.config import Config
from factory.guard import Policy, make_guard
from factory.state import RunState
from factory.tools import python_rel

READ_ONLY_TOOLS = ["Read", "Glob", "Grep"]
BUILD_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]

COMMON_RULES = """
## Rules for every factory agent
- You are one agent in an automated software factory. Other agents handle the other SDLC stages.
- Your working directory is the Corner Shop store repo: React + Vite frontend (frontend/), FastAPI API (api/),
  SQLite with SQLAlchemy and Alembic (db/), Playwright end-to-end tests (e2e/).
- Follow the existing code patterns and naming exactly. Keep changes small and focused on the requirement.
- Do not commit, branch, merge or push. The pipeline handles git.
- No network access. Do not install packages; use only what is already installed.
- When you are done, return your result in the required structured format. Keep text fields short and plain.
"""


@dataclass
class AgentSpec:
    name: str                                   # e.g. "db_agent"
    title: str                                  # shown on the dashboard, e.g. "DB Agent"
    role: str                                   # the role prompt
    output_schema: dict                         # JSON schema of what the agent writes to the run state
    task: Callable[[RunState, dict], str]       # builds the task prompt from the run state
    tools: list[str] = field(default_factory=lambda: list(READ_ONLY_TOOLS))
    writable: list[str] = field(default_factory=list)   # folders the agent may edit
    bash: list[str] = field(default_factory=list)       # allowed shell commands (regexes, {py} = store Python)
    protected: list[str] = field(default_factory=list)  # paths inside `writable` the agent still may not edit


def bash_patterns(spec: AgentSpec) -> list[str]:
    py = r"(?:\./)?" + python_rel().replace(".", r"\.")
    return [p.replace("{py}", py) for p in spec.bash]


class AgentFailed(RuntimeError):
    pass


class UsageLimitReached(AgentFailed):
    """The subscription's usage limit was hit. The run can be resumed once it resets."""


def tool_summary(block: ToolUseBlock, root: Path) -> str:
    """A one-line description of a tool call for the activity feed."""
    data = block.input
    target = data.get("file_path") or data.get("path") or data.get("notebook_path")
    if block.name == "Bash":
        return data.get("command", "")
    if block.name in ("Grep", "Glob"):
        where = f" in {short_path(target, root)}" if target else ""
        return f"{data.get('pattern', '')}{where}"
    return short_path(target, root) if target else json.dumps(data)[:120]


def short_path(path: str | None, root: Path) -> str:
    if not path:
        return ""
    p = path.replace("\\", "/")
    r = str(root).replace("\\", "/")
    return p[len(r):].lstrip("/") if p.lower().startswith(r.lower()) else p


def result_text(block: ToolResultBlock) -> str:
    content = block.content
    if isinstance(content, list):
        content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return (content or "").strip()


async def run_agent(spec: AgentSpec, state: RunState, config: Config, workspace: Path, extra: dict | None = None) -> dict:
    """Runs one agent with its own role prompt, tools and limits. Returns its structured output."""
    log = state.log
    limits = config.limits_for(spec.name)
    policy = Policy(root=workspace, writable=spec.writable, bash=bash_patterns(spec), protected=spec.protected)

    def on_deny(tool_name: str, tool_input: dict, reason: str) -> None:
        log.emit("tool_denied", spec.name, tool=tool_name, reason=reason)

    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code", "append": spec.role + COMMON_RULES},
        tools=spec.tools,
        allowed_tools=spec.tools,
        permission_mode="dontAsk",           # anything not explicitly allowed is refused, never prompted
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[make_guard(policy, on_deny)])]},
        setting_sources=[],                  # ignore user/project settings and CLAUDE.md files
        cwd=str(workspace),
        model=config.model,
        effort=config.effort,
        max_turns=limits.max_turns,
        max_budget_usd=limits.max_budget_usd,
        output_format={"type": "json_schema", "schema": spec.output_schema},
        # No MCP servers: agents must not load your claude.ai connectors (Drive, Docs, ...). Besides being
        # out of scope, their tool descriptions add ~140k tokens to every agent and burn your usage.
        strict_mcp_config=True,
        mcp_servers={},
        disallowed_tools=["mcp__*"],
        env={
            "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
            # Subscription mode passes no key, so the agent uses the Claude Code login.
            **({"ANTHROPIC_API_KEY": config.api_key} if config.auth == "api_key" else {}),
        },
        stderr=lambda line: log.emit("agent_log", spec.name, line=line),   # keep CLI noise in the log, off the screen
    )

    log.emit("agent_started", spec.name, title=spec.title, model=config.model)
    run = AgentRun(spec, log, workspace)
    try:
        async for message in query(prompt=spec.task(state, extra or {}), options=options):
            run.handle(message)
    except ClaudeSDKError as err:
        raise run.failure(str(err)) from err

    result = run.result
    if result is None:
        raise run.failure("ended without a result")
    log.emit("agent_finished", spec.name, title=spec.title, cost_usd=round(result.total_cost_usd or 0, 4),
             turns=result.num_turns, seconds=round(result.duration_ms / 1000, 1), outcome=result.subtype,
             usage=result.model_usage)
    state.update(cost_usd=round(state.get("cost_usd", 0) + (result.total_cost_usd or 0), 4))

    if result.is_error or result.structured_output is None:
        detail = "; ".join(result.errors or []) or result.result or result.subtype
        raise run.failure(f"did not finish ({result.subtype}): {detail}")
    return result.structured_output


class AgentRun:
    """Turns the SDK's messages for one agent into activity-feed events, and remembers the outcome."""

    def __init__(self, spec: AgentSpec, log, workspace: Path):
        self.spec = spec
        self.log = log
        self.workspace = workspace
        self.result: ResultMessage | None = None
        self.api_error: str | None = None       # e.g. "rate_limit", "billing_error"
        self.limit_resets_at: int | None = None

    def handle(self, message) -> None:
        name = self.spec.name
        if isinstance(message, AssistantMessage):
            if message.error:
                self.api_error = message.error
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    self.log.emit("agent_message", name, text=block.text.strip())
                elif isinstance(block, ToolUseBlock):
                    self.log.emit("tool_call", name, tool=block.name, summary=tool_summary(block, self.workspace), tool_use_id=block.id)
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    text = result_text(block)
                    self.log.emit("tool_result", name, tool_use_id=block.tool_use_id, is_error=bool(block.is_error),
                                  lines=text.count("\n") + 1 if text else 0, preview=text[:300])
        elif isinstance(message, RateLimitEvent):
            info = message.rate_limit_info
            if info.status == "rejected":
                self.limit_resets_at = info.resets_at
            self.log.emit("usage_limit", name, status=info.status, window=info.rate_limit_type,
                          utilization=info.utilization, resets_at=info.resets_at)
        elif isinstance(message, ResultMessage):
            self.result = message

    def failure(self, detail: str) -> "AgentFailed":
        """Builds a plain-English error, recognising usage limits and login problems."""
        title = self.spec.title
        if self.limit_resets_at or self.api_error == "rate_limit" or "limit" in detail.lower() and "usage" in detail.lower():
            when = f" It resets at {datetime.fromtimestamp(self.limit_resets_at):%H:%M}." if self.limit_resets_at else ""
            return UsageLimitReached(f"{title} stopped: your Claude usage limit was reached.{when}")
        if self.api_error == "authentication_failed":
            return AgentFailed(f"{title} could not log in to Claude. Run `claude`, type /login, then try again.")
        if self.api_error == "billing_error":
            return AgentFailed(f"{title} failed: the Claude account has no credit or usage left ({detail}).")
        return AgentFailed(f"{title} failed: {detail}")


# ---------- small helpers for writing JSON schemas ----------

STR = {"type": "string"}
BOOL = {"type": "boolean"}
INT = {"type": "integer"}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


def obj(**props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


def as_json(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)
