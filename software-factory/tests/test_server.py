import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from factory import state as state_module
from factory.state import RunState
from server import app as app_module
from server import stream


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(state_module, "RUNS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def launched(monkeypatch):
    """Records background launches instead of starting real factory processes."""
    calls = []
    monkeypatch.setattr(app_module.runner, "launch", lambda run_id, *args: calls.append((run_id, *args)))
    monkeypatch.setattr(app_module.runner, "active_run", lambda: None)
    monkeypatch.setattr(app_module.pipeline, "preflight", lambda: None)
    return calls


@pytest.fixture
def client(runs_dir, launched):
    with TestClient(app_module.app) as test_client:
        yield test_client


def make_run(status: str, **data) -> RunState:
    state = RunState.create("Shoppers can save products to a wishlist")
    state.update(status=status, title="Product Wishlist", **data)
    return state


def test_backlog_starts_empty(client):
    assert client.get("/api/runs").json() == []


def test_adding_a_requirement_starts_a_run(client, launched):
    response = client.post("/api/runs", json={"requirement": "Shoppers can save products to a wishlist"})

    assert response.status_code == 201
    assert response.json()["id"] == "REQ-001"
    assert response.json()["status"] == "new"
    assert launched == [("REQ-001", "execute", "REQ-001")]
    assert [r["id"] for r in client.get("/api/runs").json()] == ["REQ-001"]


def test_requirement_must_have_some_text(client):
    assert client.post("/api/runs", json={"requirement": "hi"}).status_code == 422


def test_only_one_run_at_a_time(client, monkeypatch):
    monkeypatch.setattr(app_module.runner, "active_run", lambda: "REQ-001")

    response = client.post("/api/runs", json={"requirement": "Discount codes at checkout"})

    assert response.status_code == 409
    assert "busy with REQ-001" in response.json()["detail"]


def test_get_run_returns_the_full_state(client):
    make_run("awaiting_approval", user_stories=["As a shopper..."])

    run = client.get("/api/runs/REQ-001").json()

    assert run["user_stories"] == ["As a shopper..."]
    assert run["active"] is False


@pytest.mark.parametrize("bad_id", ["REQ-999", "..%2F..%2Fsecrets", "abc"])
def test_unknown_or_unsafe_run_ids_are_404(client, bad_id):
    assert client.get(f"/api/runs/{bad_id}").status_code == 404


def test_approve_launches_the_release(client, launched):
    make_run("awaiting_approval")

    response = client.post("/api/runs/REQ-001/approve", json={"by": "Gopal"})

    assert response.status_code == 202
    assert launched == [("REQ-001", "approve", "REQ-001", "--by", "Gopal")]


def test_cannot_approve_a_run_that_is_not_at_the_gate(client, launched):
    make_run("in_progress")

    assert client.post("/api/runs/REQ-001/approve", json={"by": "Gopal"}).status_code == 409
    assert launched == []


def test_reject_marks_the_run_rejected(client):
    make_run("awaiting_approval", stages={"approval": "active"})

    response = client.post("/api/runs/REQ-001/reject", json={"by": "Gopal", "reason": "Not now"})

    assert response.status_code == 200
    assert client.get("/api/runs/REQ-001").json()["rejection_reason"] == "Not now"


def test_resume_only_for_failed_runs(client, launched):
    make_run("failed")
    assert client.post("/api/runs/REQ-001/resume").status_code == 202
    make_run("released")
    assert client.post("/api/runs/REQ-002/resume").status_code == 409


def test_releases_lists_released_runs(client):
    make_run("released", version="1.1.0", files_changed=[{"path": "a"}, {"path": "b"}], release_notes="Wishlist!")
    make_run("rejected")

    releases = client.get("/api/releases").json()

    assert len(releases) == 1
    assert releases[0]["version"] == "1.1.0"
    assert releases[0]["files_changed"] == 2


def test_event_history_hides_internal_log_lines(client):
    state = make_run("in_progress")
    state.log.emit("agent_log", "db_agent", line="debug noise")
    state.log.emit("tool_call", "db_agent", tool="Read", summary="api/models/cart.py")

    types = [e["type"] for e in client.get("/api/runs/REQ-001/events").json()]

    assert "tool_call" in types
    assert "agent_log" not in types


def test_live_stream_sends_new_events_including_new_runs(runs_dir):
    first = make_run("in_progress")
    first.log.emit("tool_call", "db_agent", tool="Read", summary="before connecting")

    async def collect():
        polls = 0

        async def disconnected():
            nonlocal polls
            polls += 1
            if polls == 2:  # events written after the client connected
                first.log.emit("tool_call", "db_agent", tool="Edit", summary="after connecting")
                RunState.create("Second requirement").log.emit("run_created", requirement="Second requirement")
            return polls > 3

        return [msg async for msg in stream.event_stream(disconnected)]

    messages = asyncio.run(collect())
    events = [json.loads(m[6:]) for m in messages if m.startswith("data: ")]

    summaries = [e.get("summary") for e in events]
    assert "before connecting" not in summaries          # history is fetched over REST, not streamed again
    assert "after connecting" in summaries
    assert any(e["run_id"] == "REQ-002" and e["type"] == "run_created" for e in events)


def test_overview_reports_factory_and_store(client, monkeypatch):
    monkeypatch.setattr(app_module, "store_api_up", lambda: False)

    data = client.get("/api/overview").json()

    assert data["factory"]["auth"] in ("subscription", "api_key")
    assert [s["id"] for s in data["stages"]][-1] == "release"
    assert data["agents"]["db_agent"] == "DB Agent"
