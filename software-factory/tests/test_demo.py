import asyncio
import json
import time

import pytest

from factory import demo
from factory import state as state_module
from factory.state import RunState

RECORDING = {
    "name": "wishlist",
    "title": "Product Wishlist",
    "requirement": "Shoppers can save products to a wishlist",
    "keywords": ["wishlist", "heart"],
    "source_run": "REQ-001",
    "diff": "diff --git a/x b/x\n+REQ-001 change\n",
    "release": {"commit": "abc", "version": "1.1.0"},
    "events_to_gate": [
        {"t": 0.0, "type": "state_updated", "agent": None, "keys": ["status", "stages", "pid"],
         "values": {"status": "in_progress", "stages": {"requirements": "waiting"}, "pid": 999}},
        {"t": 1.0, "type": "stage", "agent": None, "stage": "requirements", "title": "Requirements", "status": "active", "agents": []},
        {"t": 2.0, "type": "state_updated", "agent": "requirements_agent", "keys": ["title"], "values": {"title": "Product Wishlist"}},
        {"t": 3.0, "type": "branch_created", "agent": None, "branch": "feature/REQ-001-product-wishlist", "path": "x/REQ-001"},
        {"t": 4.0, "type": "state_updated", "agent": None, "keys": ["worktree", "branch"],
         "values": {"worktree": "C:/old/worktree", "branch": "feature/REQ-001-product-wishlist"}},
        {"t": 900.0, "type": "state_updated", "agent": None, "keys": ["status"], "values": {"status": "awaiting_approval"}},
        {"t": 900.1, "type": "gate_waiting", "agent": None, "verdict": "approve"},
    ],
    "events_release": [],
}


@pytest.fixture
def demo_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEMO_DIR", tmp_path / "demo")
    monkeypatch.setattr(state_module, "RUNS_DIR", tmp_path / "runs")
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "wishlist.json").write_text(json.dumps(RECORDING))
    (tmp_path / "demo" / "discounts.json").write_text(json.dumps({**RECORDING, "name": "discounts", "keywords": ["discount", "code"]}))
    return tmp_path


def test_typed_requirement_picks_the_matching_recording(demo_dirs):
    assert demo.choose_recording("Add discount codes at checkout")["name"] == "discounts"
    assert demo.choose_recording("A heart button to save products to a wishlist")["name"] == "wishlist"


def test_no_matching_recording_is_a_clear_error(demo_dirs):
    with pytest.raises(demo.DemoError, match="no recording matches"):
        demo.choose_recording("Product search")


def test_replay_uses_the_new_run_id():
    events = demo.for_this_run(RECORDING["events_to_gate"], "REQ-001", "REQ-007")
    assert events[3]["branch"] == "feature/REQ-007-product-wishlist"


def test_replay_reaches_the_gate_like_a_real_run(demo_dirs):
    state = RunState.create(RECORDING["requirement"])

    asyncio.run(demo.replay_to_gate(state, RECORDING, speed=1000, max_gap=0.01))

    saved = RunState.load(state.id).data
    assert saved["status"] == "awaiting_approval"
    assert saved["title"] == "Product Wishlist"
    assert saved["branch"] == f"feature/{state.id}-product-wishlist"
    assert saved["demo_recording"] == "wishlist"
    assert "worktree" not in saved                    # run-specific values from the recording are dropped
    assert saved["pid"] != 999                        # the replay process owns the run while it plays
    assert f"+{state.id} change" in (state.run_dir / "diff.patch").read_text()
    types = [json.loads(l)["type"] for l in (state.run_dir / "events.jsonl").read_text().splitlines()]
    assert types[-1] == "gate_waiting"


def test_recordings_cut_out_interrupted_attempts():
    def ev(type, **data):
        return {"type": type, **data}
    events = [
        ev("stage", stage="build", status="done"),
        ev("stage", stage="qa", status="active"),
        ev("agent_started", agent="qa_agent"),
        ev("stage", stage="qa", status="failed"),
        ev("run_failed", error="usage limit"),
        ev("run_resumed", stage="qa"),
        ev("state_updated", values={"status": "in_progress"}),
        ev("stage", stage="qa", status="active"),
        ev("agent_started", agent="qa_agent", second=True),
    ]
    kept = demo.without_interruptions(events)
    assert [e["type"] for e in kept] == ["stage", "state_updated", "stage", "agent_started"]
    assert kept[-1].get("second") is True


def test_long_recorded_pauses_are_shortened(demo_dirs):
    state = RunState.create(RECORDING["requirement"])
    t0 = time.time()
    asyncio.run(demo.replay_to_gate(state, RECORDING, speed=1, max_gap=0.05))
    assert time.time() - t0 < 2   # 900 recorded seconds play back in well under 2
