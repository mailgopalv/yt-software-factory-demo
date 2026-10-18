"""Deterministic tools the pipeline uses: git and worktrees, test runners, backups and releases.

These are plain Python, not AI. The agents decide *what* to change; these helpers do the
mechanical steps the same way every time.
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

IS_WINDOWS = os.name == "nt"
FACTORY_AUTHOR = ["-c", "user.name=AI Software Factory", "-c", "user.email=factory@localhost"]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Installed packages are shared with the feature worktree instead of being reinstalled.
SHARED_INSTALLS = [".venv", "frontend/node_modules", "e2e/node_modules"]


class ToolError(RuntimeError):
    pass


# ---------- paths and commands ----------

def python_rel() -> str:
    """The store's Python, relative to the store folder (as agents type it in Bash)."""
    return ".venv/Scripts/python.exe" if IS_WINDOWS else ".venv/bin/python"


def store_python(root: Path) -> str:
    return str(root / python_rel())


def npx() -> str:
    return shutil.which("npx") or "npx"


def npm() -> str:
    return shutil.which("npm") or "npm"


def claude_cli() -> str:
    """The Claude Code program the Agent SDK runs (bundled with the SDK)."""
    import claude_agent_sdk
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if IS_WINDOWS else "claude")
    return str(bundled) if bundled.exists() else (shutil.which("claude") or "claude")


def claude_login_status() -> dict:
    """Asks Claude Code whether it is logged in, e.g. {"loggedIn": true, "subscriptionType": "pro", ...}."""
    try:
        return json.loads(run([claude_cli(), "auth", "status"], Path.home(), check=False, timeout=30) or "{}")
    except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired):
        return {}


def run(cmd: list[str], cwd: Path, check: bool = True, env: dict | None = None, timeout: int = 600) -> str:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, **(env or {})}, timeout=timeout,
    )
    if check and result.returncode != 0:
        raise ToolError(f"{' '.join(cmd)} failed:\n{result.stdout}\n{result.stderr}".strip())
    return result.stdout


def git(cwd: Path, *args: str, check: bool = True) -> str:
    return run(["git", *args], cwd, check=check).strip()


# ---------- feature branches in a separate worktree ----------

def slugify(text: str, max_len: int = 30) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "change"


def worktree_path(store: Path, branch: str) -> Path:
    return store / ".worktrees" / branch.split("/")[-1]


def create_worktree(store: Path, branch: str, base: str) -> Path:
    """Creates the feature branch in its own folder so the live store stays on main."""
    path = worktree_path(store, branch)
    exclude = store / ".git" / "info" / "exclude"
    if "/.worktrees/" not in exclude.read_text(encoding="utf-8", errors="replace"):
        with exclude.open("a", encoding="utf-8") as f:
            f.write("\n/.worktrees/\n")
    if path.exists():
        remove_worktree(store, path)
    git(store, "worktree", "prune")
    if git(store, "branch", "--list", branch):
        git(store, "branch", "-D", branch)
    git(store, "worktree", "add", "-b", branch, str(path), base)
    for rel in SHARED_INSTALLS:
        link_dir(store / rel, path / rel)
    return path


def attach_worktree(store: Path, branch: str) -> Path:
    """Re-opens an existing feature branch's worktree (used when a run is resumed)."""
    path = worktree_path(store, branch)
    if path.exists():
        return path
    git(store, "worktree", "prune")
    git(store, "worktree", "add", str(path), branch)
    for rel in SHARED_INSTALLS:
        link_dir(store / rel, path / rel)
    return path


def link_dir(target: Path, link: Path) -> None:
    if not target.exists():
        raise ToolError(f"{target} is missing. Run the store's setup script first.")
    if IS_WINDOWS:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def unlink_dir(link: Path) -> None:
    """Removes a junction/symlink without touching what it points to."""
    if not os.path.lexists(link):
        return
    if IS_WINDOWS:
        os.rmdir(link)  # removes the junction itself, never the target's contents
    else:
        os.unlink(link)


def remove_worktree(store: Path, path: Path) -> None:
    for rel in SHARED_INSTALLS:
        unlink_dir(path / rel)  # must happen first, or removing the worktree could follow the links
    git(store, "worktree", "remove", "--force", str(path), check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    git(store, "worktree", "prune")


def commit_all(workspace: Path, message: str) -> str | None:
    """Commits everything in the workspace as the factory. Returns the commit id, or None if nothing changed."""
    git(workspace, "add", "-A")
    if not git(workspace, "status", "--porcelain"):
        return None
    git(workspace, *FACTORY_AUTHOR, "commit", "-q", "-m", message)
    return git(workspace, "rev-parse", "--short", "HEAD")


def diff(workspace: Path, base: str) -> dict:
    """The feature's full diff against main, plus a per-file summary."""
    files = []
    for line in git(workspace, "diff", "--numstat", f"{base}...HEAD").splitlines():
        added, removed, path = line.split("\t", 2)
        files.append({"path": path, "added": int(added) if added != "-" else 0, "removed": int(removed) if removed != "-" else 0})
    return {"patch": git(workspace, "diff", f"{base}...HEAD"), "files": files}


# ---------- tests ----------

SUITES = {
    "api": "API (pytest)",
    "ui": "UI (Vitest)",
    "e2e": "E2E (Playwright)",
}


def suite_command(tier: str, workspace: Path, report: Path) -> tuple[list[str], Path, dict]:
    if tier == "api":
        return [store_python(workspace), "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"], workspace, {}
    if tier == "ui":
        return [npx(), "vitest", "run", "--reporter=default", "--reporter=json", f"--outputFile.json={report}"], workspace / "frontend", {}
    if tier == "e2e":
        env = {"PLAYWRIGHT_JSON_OUTPUT_FILE": str(report), "PLAYWRIGHT_JSON_OUTPUT_NAME": str(report)}
        return [npx(), "playwright", "test", "--reporter=list,json"], workspace / "e2e", env
    raise ValueError(tier)


def parse_report(tier: str, report: Path) -> dict:
    """Reads passed/failed counts from each runner's machine-readable report."""
    if not report.exists():
        return {"passed": 0, "failed": 0, "total": 0}
    if tier == "api":
        root = ET.parse(report).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        total = sum(int(s.get("tests", 0)) - int(s.get("skipped", 0)) for s in suites)
        failed = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
        return {"passed": total - failed, "failed": failed, "total": total}
    data = json.loads(report.read_text(encoding="utf-8"))
    if tier == "ui":
        return {"passed": data["numPassedTests"], "failed": data["numFailedTests"] + data.get("numRuntimeErrorTestSuites", 0), "total": data["numTotalTests"]}
    stats = data.get("stats", {})
    passed = stats.get("expected", 0) + stats.get("flaky", 0)
    failed = stats.get("unexpected", 0)
    return {"passed": passed, "failed": failed, "total": passed + failed}


async def run_suite(tier: str, workspace: Path, out_dir: Path, on_line: Callable[[str], None]) -> dict:
    """Runs one test suite, streaming its output line by line. Returns the counts and the output tail."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / f"{tier}-{int(time.time() * 1000)}.{'xml' if tier == 'api' else 'json'}"
    cmd, cwd, extra_env = suite_command(tier, workspace, report)
    env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1", **extra_env}

    started = time.time()
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    lines: list[str] = []
    try:
        async with asyncio.timeout(600):
            async for raw in proc.stdout:
                line = ANSI.sub("", raw.decode("utf-8", errors="replace")).rstrip()
                lines.append(line)
                if line.strip():
                    on_line(line)
            await proc.wait()
    except TimeoutError:
        proc.kill()
        lines.append("Test run timed out after 10 minutes.")

    counts = parse_report(tier, report)
    ok = proc.returncode == 0 and counts["failed"] == 0 and counts["total"] > 0
    return {
        "tier": tier,
        "name": SUITES[tier],
        "ok": ok,
        **counts,
        "seconds": round(time.time() - started, 1),
        "output_tail": "\n".join(lines[-120:]),
    }


# ---------- database ----------

def alembic(workspace: Path, *args: str) -> str:
    return run([store_python(workspace), "-m", "alembic", "-c", "db/alembic.ini", *args], workspace)


def migration_head(workspace: Path) -> str:
    """The newest migration revision, e.g. '0001'."""
    out = alembic(workspace, "heads")
    return out.split()[0] if out.strip() else ""


def migration_sql(workspace: Path, from_revision: str) -> str:
    """The SQL the new migrations will run, previewed without touching any database."""
    if migration_head(workspace) == from_revision:
        return ""
    try:
        sql = alembic(workspace, "upgrade", f"{from_revision}:head", "--sql")
    except ToolError as err:
        return f"-- Could not render SQL preview: {err}"
    keep = [l for l in sql.splitlines() if l.strip() and "alembic_version" not in l and not l.startswith("INFO")]
    return "\n".join(keep)


def backup_db(store: Path, label: str) -> Path | None:
    db = store / "db" / "store.db"
    if not db.exists():
        return None
    backups = store / "db" / "backups"
    backups.mkdir(exist_ok=True)
    target = backups / f"store-{datetime.now():%Y%m%d-%H%M%S}-before-{label}.db"
    shutil.copy2(db, target)
    return target


def migrate_live_db(store: Path) -> str:
    if (store / "db" / "store.db").exists():
        alembic(store, "upgrade", "head")
        # New tables may come with seed data (e.g. discount codes). The store's seed script only fills
        # tables that are still empty, so existing data is never touched.
        run([store_python(store), "-m", "db.seed"], store)
        return "Database upgraded to the latest migration, new seed data added"
    run([store_python(store), "-m", "db.reset_db"], store)
    return "Database created from migrations and seed data"


# ---------- release ----------

def read_version(workspace: Path) -> str:
    return (workspace / "VERSION").read_text(encoding="utf-8").strip()


def next_minor_version(version: str) -> str:
    major, minor, _patch = (int(x) for x in version.split("."))
    return f"{major}.{minor + 1}.0"


def write_version(workspace: Path, version: str) -> None:
    (workspace / "VERSION").write_text(version + "\n", encoding="utf-8")
    package = workspace / "frontend" / "package.json"
    text = package.read_text(encoding="utf-8")
    package.write_text(re.sub(r'"version":\s*"[^"]+"', f'"version": "{version}"', text, count=1), encoding="utf-8")


def store_is_clean(store: Path) -> bool:
    return not git(store, "status", "--porcelain", "--untracked-files=no")


def merge_to_main(store: Path, branch: str, message: str) -> str:
    git(store, *FACTORY_AUTHOR, "merge", "--no-ff", branch, "-m", message)
    return git(store, "rev-parse", "--short", "HEAD")


def build_frontend(store: Path) -> None:
    run([npm(), "--prefix", "frontend", "run", "build"], store)


def reload_api(store: Path, api_url: str, version: str, timeout: float = 25) -> str:
    """The store API runs with --reload: touching main.py restarts it. Waits until it reports the new version."""
    os.utime(store / "api" / "main.py")
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{api_url}/api/health", timeout=2) as resp:
                if json.load(resp).get("version") == version:
                    return f"API restarted and serving v{version}"
        except Exception as err:  # noqa: BLE001 (connection refused while restarting is expected)
            last_error = str(err)
        time.sleep(1)
    if "refused" in last_error.lower() or "10061" in last_error:
        return "Store API is not running. Start it with run-store to see the release."
    return f"API did not report v{version} within {timeout:.0f}s ({last_error or 'old version still running'})"


def tag(store: Path, name: str, message: str) -> None:
    git(store, *FACTORY_AUTHOR, "tag", "-a", name, "-m", message)
