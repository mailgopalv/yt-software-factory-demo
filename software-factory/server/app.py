"""Factory server. Run from the software-factory folder: uvicorn server.app:app --port 8000

  GET  /                         the dashboard
  GET  /api/overview             factory settings, store version, which run is active
  GET  /api/runs                 the backlog: every requirement and its status
  POST /api/runs                 add a requirement and start the agents
  GET  /api/runs/{id}            a run's full state (everything the agents wrote)
  GET  /api/runs/{id}/events     a run's event history
  GET  /api/runs/{id}/diff       the red/green diff for review
  POST /api/runs/{id}/approve    the human gate: approve and release
  POST /api/runs/{id}/reject     the human gate: reject and discard
  POST /api/runs/{id}/resume     continue a failed run
  GET  /api/releases             release history
  GET  /api/events               live event stream (Server-Sent Events)
"""
import json
import re
import urllib.request
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from factory import demo
from factory.agents import AGENTS
from factory.config import FACTORY_DIR, load_config
from factory.pipeline import STAGES, Pipeline, PipelineError
from factory.state import RunState, list_runs
from server.runner import FactoryBusy, Runner
from server.stream import HIDDEN_EVENTS, event_stream

DASHBOARD = FACTORY_DIR / "dashboard" / "index.html"
RUN_ID = r"^REQ-\d{3,}$"

config = load_config()
pipeline = Pipeline(config)
runner = Runner()


@asynccontextmanager
async def lifespan(app: FastAPI):
    runner.mark_interrupted()  # runs left "in progress" by a crashed process become resumable
    yield


app = FastAPI(title="AI Software Factory", version="1.0.0", lifespan=lifespan)


class NewRequirement(BaseModel):
    requirement: str = Field(min_length=5, max_length=2000)


class Decision(BaseModel):
    by: str = Field(default="Gopal", min_length=1, max_length=60)
    reason: str = Field(default="", max_length=500)


# ---------- helpers ----------

def check_id(run_id: str) -> str:
    """Run ids come from the URL; only REQ-<number> is accepted, so they can't point outside runs/."""
    if not re.fullmatch(RUN_ID, run_id):
        raise HTTPException(status_code=404, detail=f"No run called {run_id}")
    return run_id


def load_run(run_id: str) -> RunState:
    try:
        return RunState.load(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No run called {run_id}") from None


def summary(run: dict) -> dict:
    """The backlog view of a run: enough for a card, without the agents' full output."""
    return {
        "id": run["id"],
        "title": run.get("title"),
        "requirement": run["requirement"],
        "status": run["status"],
        "stages": run.get("stages", {}),
        "iteration": run.get("iteration", 0),
        "verdict": run.get("verdict"),
        "version": run.get("version"),
        "branch": run.get("branch"),
        "cost_usd": run.get("cost_usd", 0),
        "started_at": run.get("started_at"),
        "released_at": run.get("released_at"),
        "error": run.get("error"),
    }


def store_api_up() -> bool:
    try:
        with urllib.request.urlopen(f"{config.api_url}/api/health", timeout=0.5) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def busy_error(err: FactoryBusy) -> HTTPException:
    return HTTPException(status_code=409, detail=str(err))


# ---------- pages ----------

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(DASHBOARD)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/overview")
def overview():
    runner.mark_interrupted()
    version_file = config.store_path / "VERSION"
    return {
        "factory": {"model": config.model, "effort": config.effort, "auth": config.auth, "qa_max_loops": config.qa_max_loops},
        "demo": {
            "enabled": config.demo_enabled,
            "show_badge": config.demo_show_badge,
            "speed": config.demo_speed,
            "recordings": [{"name": r["name"], "title": r["title"], "keywords": r["keywords"]} for r in demo.recordings()],
        },
        "store": {
            "path": str(config.store_path),
            "version": version_file.read_text(encoding="utf-8").strip() if version_file.exists() else None,
            "web_url": config.web_url,
            "api_url": config.api_url,
            "api_up": store_api_up(),
        },
        "stages": [{"id": k, "title": v[0], "agents": v[1]} for k, v in STAGES.items()],
        "agents": {name: spec.title for name, spec in AGENTS.items()},
        "active_run": runner.active_run(),
    }


# ---------- runs ----------

@app.get("/api/runs")
def get_runs():
    runner.mark_interrupted()
    return [summary(run) for run in reversed(list_runs())]


@app.post("/api/runs", status_code=201)
def create_run(body: NewRequirement):
    busy = runner.active_run()
    if busy:
        raise busy_error(FactoryBusy(busy))
    try:
        state = pipeline.create_run(body.requirement.strip())
    except PipelineError as err:
        raise HTTPException(status_code=400, detail=str(err)) from None
    try:
        runner.launch(state.id, "execute", state.id)
    except FactoryBusy as err:
        raise busy_error(err) from None
    return summary(state.data)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    runner.mark_interrupted()
    state = load_run(check_id(run_id))
    return {**state.data, "active": runner.active_run() == run_id}


@app.get("/api/runs/{run_id}/events")
def get_events(run_id: str):
    state = load_run(check_id(run_id))
    path = state.run_dir / "events.jsonl"
    if not path.exists():
        return []
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [e for e in events if e.get("type") not in HIDDEN_EVENTS]


@app.get("/api/runs/{run_id}/diff", response_class=PlainTextResponse)
def get_diff(run_id: str):
    state = load_run(check_id(run_id))
    path = state.run_dir / "diff.patch"
    return path.read_text(encoding="utf-8") if path.exists() else ""


@app.post("/api/runs/{run_id}/approve", status_code=202)
def approve(run_id: str, body: Decision):
    state = load_run(check_id(run_id))
    if state["status"] != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"{run_id} is {state['status']}, not awaiting approval.")
    try:
        runner.launch(run_id, "approve", run_id, "--by", body.by)
    except FactoryBusy as err:
        raise busy_error(err) from None
    return {"id": run_id, "status": "releasing", "approved_by": body.by}


@app.post("/api/runs/{run_id}/reject")
def reject(run_id: str, body: Decision):
    load_run(check_id(run_id))
    try:
        state = pipeline.reject(run_id, body.by, body.reason)
    except PipelineError as err:
        raise HTTPException(status_code=409, detail=str(err)) from None
    return summary(state.data)


@app.post("/api/runs/{run_id}/resume", status_code=202)
def resume(run_id: str):
    state = load_run(check_id(run_id))
    if state["status"] != "failed" or state.get("approved_at"):
        raise HTTPException(status_code=409, detail=f"{run_id} can't be resumed (status: {state['status']}).")
    try:
        runner.launch(run_id, "resume", run_id)
    except FactoryBusy as err:
        raise busy_error(err) from None
    return {"id": run_id, "status": "resuming"}


@app.get("/api/releases")
def releases():
    released = [run for run in reversed(list_runs()) if run["status"] == "released"]
    return [
        {
            "id": run["id"],
            "version": run.get("version"),
            "title": run.get("title"),
            "released_at": run.get("released_at"),
            "approved_by": run.get("approved_by"),
            "files_changed": len(run.get("files_changed", [])),
            "release_notes": run.get("release_notes"),
            "highlights": run.get("highlights", []),
            "store_url": config.web_url,
        }
        for run in released
    ]


@app.get("/api/events")
async def events(request: Request, run_id: str | None = None, replay: bool = False):
    if run_id:
        check_id(run_id)
    return StreamingResponse(
        event_stream(request.is_disconnected, run_id, replay),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
