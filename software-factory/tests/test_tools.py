import json
import subprocess
from pathlib import Path

import pytest

from factory import tools


def test_slugify():
    assert tools.slugify("Wishlist") == "wishlist"
    assert tools.slugify("Discount codes at checkout!") == "discount-codes-at-checkout"


def test_next_minor_version():
    assert tools.next_minor_version("1.0.0") == "1.1.0"
    assert tools.next_minor_version("1.9.3") == "1.10.0"


def test_parse_pytest_report(tmp_path):
    report = tmp_path / "api.xml"
    report.write_text('<testsuites><testsuite tests="20" failures="2" errors="1" skipped="0"/></testsuites>')
    assert tools.parse_report("api", report) == {"passed": 17, "failed": 3, "total": 20}


def test_parse_vitest_report(tmp_path):
    report = tmp_path / "ui.json"
    report.write_text(json.dumps({"numTotalTests": 12, "numPassedTests": 11, "numFailedTests": 1}))
    assert tools.parse_report("ui", report) == {"passed": 11, "failed": 1, "total": 12}


def test_parse_playwright_report(tmp_path):
    report = tmp_path / "e2e.json"
    report.write_text(json.dumps({"stats": {"expected": 5, "unexpected": 1, "flaky": 0, "skipped": 0}}))
    assert tools.parse_report("e2e", report) == {"passed": 5, "failed": 1, "total": 6}


def test_missing_report_counts_as_nothing_run(tmp_path):
    assert tools.parse_report("api", tmp_path / "missing.xml")["total"] == 0


def test_write_version(tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "VERSION").write_text("1.0.0\n")
    (tmp_path / "frontend" / "package.json").write_text('{\n  "name": "x",\n  "version": "1.0.0",\n  "deps": {"a": {"version": "9"}}\n}\n')
    tools.write_version(tmp_path, "1.1.0")
    assert tools.read_version(tmp_path) == "1.1.0"
    package = json.loads((tmp_path / "frontend" / "package.json").read_text())
    assert package["version"] == "1.1.0"
    assert package["deps"]["a"]["version"] == "9"


@pytest.fixture
def fake_store(tmp_path):
    """A tiny git repo with the folders the worktree links to."""
    store = tmp_path / "store"
    for rel in tools.SHARED_INSTALLS:
        (store / rel).mkdir(parents=True)
        (store / rel / "keep.txt").write_text("installed package")
    (store / "frontend" / "app.js").write_text("app")
    (store / "e2e" / "spec.js").write_text("spec")
    (store / ".gitignore").write_text(".venv/\nnode_modules/\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=store, check=True)
    subprocess.run(["git", "add", "-A"], cwd=store, check=True)
    subprocess.run(["git", *tools.FACTORY_AUTHOR, "commit", "-q", "-m", "init"], cwd=store, check=True)
    return store


def test_worktree_shares_installs_and_cleanup_keeps_them(fake_store):
    worktree = tools.create_worktree(fake_store, "feature/REQ-001-wishlist", "main")

    assert worktree == fake_store / ".worktrees" / "REQ-001-wishlist"
    assert (worktree / ".venv" / "keep.txt").read_text() == "installed package"
    assert tools.git(fake_store, "branch", "--list", "feature/REQ-001-wishlist")

    (worktree / "frontend" / "new.js").write_text("feature")
    assert tools.commit_all(worktree, "REQ-001 ui: add feature") is not None
    assert tools.commit_all(worktree, "nothing to commit") is None

    tools.remove_worktree(fake_store, worktree)

    assert not worktree.exists()
    for rel in tools.SHARED_INSTALLS:
        assert (fake_store / rel / "keep.txt").exists(), f"{rel} was deleted with the worktree!"
    assert not (fake_store / "frontend" / "new.js").exists()  # the feature stays on its branch


def test_diff_lists_changed_files(fake_store):
    worktree = tools.create_worktree(fake_store, "feature/REQ-002-x", "main")
    (worktree / "frontend" / "app.js").write_text("app\nchanged\n")
    tools.commit_all(worktree, "change")

    changes = tools.diff(worktree, "main")

    assert changes["files"] == [{"path": "frontend/app.js", "added": 2, "removed": 1}]
    assert "+changed" in changes["patch"]
    tools.remove_worktree(fake_store, worktree)
