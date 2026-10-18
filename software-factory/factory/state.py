"""The shared run state: one JSON object per requirement, saved as runs/<id>/state.json.

Each agent adds its own keys (user_stories, api_contract, db_changes, ...). The next agent
reads what earlier agents wrote.
"""
import json
import os
import re
import time
from pathlib import Path

from factory.config import RUNS_DIR
from factory.events import EventLog, Listener


class RunState:
    def __init__(self, run_dir: Path, data: dict, log: EventLog):
        self.run_dir = run_dir
        self.data = data
        self.log = log

    @property
    def id(self) -> str:
        return self.data["id"]

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def update(self, agent: str | None = None, **values) -> None:
        """Writes keys to the run state, saves it, and emits a state_updated event."""
        self.data.update(values)
        self.save()
        self.log.emit("state_updated", agent, keys=list(values), values=values)

    def save(self) -> None:
        path = self.run_dir / "state.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        retry(lambda: os.replace(tmp, path))  # Windows refuses the swap while a reader has the file open

    @classmethod
    def create(cls, requirement: str, listeners: list[Listener] | None = None) -> "RunState":
        RUNS_DIR.mkdir(exist_ok=True)
        run_id = next_run_id()
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir()
        state = cls(run_dir, {"id": run_id, "requirement": requirement, "status": "new"}, EventLog(run_id, run_dir, listeners))
        state.save()
        return state

    @classmethod
    def load(cls, run_id: str, listeners: list[Listener] | None = None) -> "RunState":
        run_dir = RUNS_DIR / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"No run called {run_id} in {RUNS_DIR}")
        return cls(run_dir, read_json(run_dir / "state.json"), EventLog(run_id, run_dir, listeners))


def next_run_id() -> str:
    numbers = [int(m.group(1)) for p in RUNS_DIR.glob("REQ-*") if (m := re.fullmatch(r"REQ-(\d+)", p.name))]
    return f"REQ-{max(numbers, default=0) + 1:03d}"


def list_runs() -> list[dict]:
    runs = []
    for path in sorted(RUNS_DIR.glob("REQ-*/state.json")):
        runs.append(read_json(path))
    return runs


def read_json(path: Path) -> dict:
    """Reads a state file, retrying briefly if a run is writing it at the same moment."""
    return retry(lambda: json.loads(path.read_text(encoding="utf-8")))


def retry(action, attempts: int = 20, wait: float = 0.05):
    for attempt in range(attempts):
        try:
            return action()
        except (json.JSONDecodeError, PermissionError):
            if attempt == attempts - 1:
                raise
            time.sleep(wait)
