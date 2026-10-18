"""The safety guard: a PreToolUse hook that checks every tool call an agent makes.

Hooks run before Claude Code's own permission rules, and a deny here applies in every
permission mode. The guard enforces:
  - reads only inside the agent's workspace (the store repo or its feature worktree)
  - edits only inside the folders that agent owns (e.g. db_agent: db/ and api/models/)
  - shell commands only from the agent's allow-list (no network, no git push, no rm)
"""
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

READ_TOOLS = {"Read", "Glob", "Grep"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
NEVER_WRITE = (".git", ".venv", "node_modules", ".worktrees")

# Shell features that could escape the allow-list: redirects, substitution, background jobs.
SHELL_ESCAPES = re.compile(r"[<>`]|\$\(|(?<!&)&(?!&)")
COMMAND_SEPARATORS = re.compile(r"&&|\|\||;|\|")
SAFE_CD = re.compile(r"cd [\w./-]+")


@dataclass
class Policy:
    root: Path                                          # the agent's workspace
    writable: list[str] = field(default_factory=list)   # path prefixes relative to root, e.g. "db/"
    bash: list[str] = field(default_factory=list)       # regexes; each command must fully match one
    protected: list[str] = field(default_factory=list)  # path prefixes inside `writable` the agent still may not edit


def to_path(raw: str, root: Path) -> Path:
    """Resolves a tool's path argument. Accepts Windows paths and Git Bash style /c/... paths."""
    m = re.match(r"^/([a-zA-Z])/(.*)", raw)
    if m and os.name == "nt":
        raw = f"{m.group(1)}:/{m.group(2)}"
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return Path(os.path.normpath(path))


def relative_to_root(path: Path, root: Path) -> str | None:
    """Returns the path relative to root using forward slashes, or None if it is outside."""
    try:
        rel = Path(os.path.normcase(path)).relative_to(Path(os.path.normcase(os.path.normpath(root))))
    except ValueError:
        return None
    return rel.as_posix()


def check(tool_name: str, tool_input: dict, policy: Policy) -> str | None:
    """Returns a reason to deny the tool call, or None to let it through."""
    if tool_name in READ_TOOLS or tool_name in WRITE_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
        if not raw:
            return None  # Glob/Grep without a path search the workspace itself
        rel = relative_to_root(to_path(raw, policy.root), policy.root)
        if rel is None:
            return f"{raw} is outside your workspace ({policy.root}). Stay inside the store repo."
        if tool_name in WRITE_TOOLS:
            rel_lower = rel.lower()
            if any(part in NEVER_WRITE for part in Path(rel_lower).parts):
                return f"You may not change files in {rel}."
            if not any(rel_lower == w.lower().rstrip("/") or rel_lower.startswith(w.lower()) for w in policy.writable):
                allowed = ", ".join(policy.writable) or "nothing (you are read-only)"
                return f"You may not edit {rel}. You may only edit: {allowed}"
            if any(rel_lower.startswith(p.lower()) for p in policy.protected):
                return f"{rel} belongs to QA and is the specification. Fix the code, not the acceptance tests."
        return None

    if tool_name == "Bash":
        return check_command(tool_input.get("command", ""), policy)

    if tool_name.startswith("mcp__"):
        return "External connectors (MCP tools) are not available to factory agents."

    return None


def check_command(command: str, policy: Policy) -> str | None:
    cleaned = command.replace("2>&1", "").strip()
    allowed = "; ".join(policy.bash) or "none"
    if SHELL_ESCAPES.search(cleaned):
        return "Redirects, background jobs and command substitution are not allowed. Run plain commands only."
    for part in COMMAND_SEPARATORS.split(cleaned):
        part = part.strip()
        if not part:
            continue
        if part.startswith("cd ") and cd_stays_inside(part[3:], policy.root):
            continue
        if not any(re.fullmatch(pattern, part) for pattern in policy.bash):
            return (
                f"Command not allowed: `{part}`. Use the Read, Glob and Grep tools to explore. "
                f"Allowed commands: {allowed}"
            )
    return None


def cd_stays_inside(target: str, root: Path) -> bool:
    """Allows `cd` to a folder inside the workspace, given as a relative or absolute path."""
    target = target.strip().strip('"').strip("'")
    if not target or target.startswith("~") or not SAFE_CD.fullmatch(f"cd {target}".replace(":", "")):
        return False
    return relative_to_root(to_path(target, root), root) is not None


def make_guard(policy: Policy, on_deny: Callable[[str, dict, str], None]):
    """Builds the async PreToolUse hook the Claude Agent SDK calls before every tool use."""

    async def guard(hook_input, tool_use_id, context):
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {}) or {}
        reason = check(tool_name, tool_input, policy)
        if reason is None:
            return {}
        on_deny(tool_name, tool_input, reason)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return guard
