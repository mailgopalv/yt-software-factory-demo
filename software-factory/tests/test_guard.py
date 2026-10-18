from pathlib import Path

import pytest

from factory.agents import AGENTS
from factory.agents.base import bash_patterns
from factory.guard import Policy, check
from factory.tools import python_rel

ROOT = Path("C:/repo/store") if Path("C:/").exists() else Path("/repo/store")


def policy_for(agent_name: str) -> Policy:
    spec = AGENTS[agent_name]
    return Policy(root=ROOT, writable=spec.writable, bash=bash_patterns(spec), protected=spec.protected)


def test_read_inside_workspace_is_allowed():
    assert check("Read", {"file_path": str(ROOT / "api" / "main.py")}, policy_for("codebase_analyst")) is None


def test_read_outside_workspace_is_denied():
    reason = check("Read", {"file_path": str(ROOT.parent / "secrets.txt")}, policy_for("codebase_analyst"))
    assert "outside your workspace" in reason


def test_relative_path_escaping_workspace_is_denied():
    assert check("Grep", {"pattern": "x", "path": "../.."}, policy_for("codebase_analyst")) is not None


def test_read_only_agent_cannot_edit():
    reason = check("Edit", {"file_path": str(ROOT / "api" / "main.py")}, policy_for("codebase_analyst"))
    assert "read-only" in reason


@pytest.mark.parametrize("path, allowed", [
    ("db/migrations/versions/0002_wishlist.py", True),
    ("api/models/wishlist.py", True),
    ("api/routes/wishlist.py", False),
    ("frontend/src/App.jsx", False),
])
def test_db_agent_edits_only_its_tier(path, allowed):
    reason = check("Write", {"file_path": str(ROOT / path)}, policy_for("db_agent"))
    assert (reason is None) == allowed


def test_nobody_edits_installed_packages():
    reason = check("Write", {"file_path": str(ROOT / "frontend" / "src" / "node_modules" / "x.js")}, policy_for("frontend_agent"))
    assert reason is not None


def test_release_agent_edits_only_changelog():
    assert check("Edit", {"file_path": str(ROOT / "CHANGELOG.md")}, policy_for("release_agent")) is None
    assert check("Edit", {"file_path": str(ROOT / "VERSION")}, policy_for("release_agent")) is not None


@pytest.mark.parametrize("command", [
    f"{python_rel()} -m pytest -q",
    f"./{python_rel()} -m pytest api/tests/test_wishlist.py -q 2>&1",
    f"{python_rel()} -m db.reset_db && {python_rel()} -m pytest -q",
])
def test_db_agent_allowed_commands(command):
    assert check("Bash", {"command": command}, policy_for("db_agent")) is None


@pytest.mark.parametrize("command", [
    "curl https://example.com",
    "git push origin main",
    "rm -rf .",
    f"{python_rel()} -m pytest; rm -rf /",
    f"{python_rel()} -m pytest > /tmp/out.txt",
    f"{python_rel()} -c \"import os; os.remove('x')\"",
    f"echo $(cat ~/.ssh/id_rsa)",
    "cd .. && ls",
])
def test_dangerous_commands_are_denied(command):
    assert check("Bash", {"command": command}, policy_for("db_agent")) is not None


def test_frontend_agent_writes_ui_and_e2e_tests_only():
    policy = policy_for("frontend_agent")
    assert check("Write", {"file_path": str(ROOT / "e2e" / "tests" / "wishlist.spec.js")}, policy) is None
    assert check("Edit", {"file_path": str(ROOT / "e2e" / "playwright.config.js")}, policy) is not None
    assert check("Edit", {"file_path": str(ROOT / "api" / "main.py")}, policy) is not None


def test_frontend_agent_can_run_its_tests():
    assert check("Bash", {"command": "npm --prefix frontend test"}, policy_for("frontend_agent")) is None
    assert check("Bash", {"command": "npm --prefix e2e test"}, policy_for("frontend_agent")) is None
    assert check("Bash", {"command": "cd e2e && npx playwright test tests/wishlist.spec.js"}, policy_for("frontend_agent")) is None
    assert check("Bash", {"command": "cd frontend && npx vitest run src/__tests__/Wishlist.test.jsx"}, policy_for("frontend_agent")) is None


@pytest.mark.parametrize("target, allowed", [
    ("frontend", True),
    (f'"{ROOT.as_posix()}"', True),
    (f'"{(ROOT / "frontend").as_posix()}"', True),
    ("..", False),
    (f'"{ROOT.parent.as_posix()}"', False),
    ("~", False),
])
def test_cd_only_inside_the_workspace(target, allowed):
    reason = check("Bash", {"command": f"cd {target} && npm test"}, policy_for("frontend_agent"))
    assert (reason is None) == allowed


def test_connector_tools_are_denied():
    reason = check("mcp__claude_ai_Google_Drive__search", {"query": "x"}, policy_for("backend_agent"))
    assert "connectors" in reason


def test_reviewer_can_diff_but_not_change_history():
    assert check("Bash", {"command": "git diff main...HEAD"}, policy_for("reviewer_agent")) is None
    assert check("Bash", {"command": "git reset --hard main"}, policy_for("reviewer_agent")) is not None
    assert check("Bash", {"command": "git commit -am x"}, policy_for("reviewer_agent")) is not None


def test_backend_agent_cannot_edit_qa_acceptance_tests():
    policy = policy_for("backend_agent")
    assert check("Edit", {"file_path": str(ROOT / "api" / "tests" / "test_wishlist.py")}, policy) is None
    reason = check("Edit", {"file_path": str(ROOT / "api" / "tests" / "test_acceptance_discount_codes.py")}, policy)
    assert "belongs to QA" in reason


def test_qa_author_edits_only_its_acceptance_file():
    from factory.agents.qa_agent import AUTHOR_SPEC

    class FakeState(dict):
        id = "REQ-002"

    spec = AUTHOR_SPEC.for_run(FakeState(title="Discount codes"))
    policy = Policy(root=ROOT, writable=spec.writable, bash=bash_patterns(spec))
    assert spec.writable == ["api/tests/test_acceptance_discount_codes.py"]
    assert check("Write", {"file_path": str(ROOT / "api" / "tests" / "test_acceptance_discount_codes.py")}, policy) is None
    assert check("Edit", {"file_path": str(ROOT / "api" / "routes" / "cart.py")}, policy) is not None
