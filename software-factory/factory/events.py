"""The event log: every step of a run is an event.

Events are appended to runs/<id>/events.jsonl (with timestamps, so a real run can be replayed
later as a demo recording) and passed to listeners such as the console printer or the
dashboard's live stream.
"""
import json
import time
from collections.abc import Callable
from pathlib import Path

Listener = Callable[[dict], None]


class EventLog:
    def __init__(self, run_id: str, run_dir: Path, listeners: list[Listener] | None = None):
        self.run_id = run_id
        self.path = run_dir / "events.jsonl"
        self.listeners = list(listeners or [])

    def emit(self, type: str, agent: str | None = None, **data) -> dict:
        event = {"ts": round(time.time(), 3), "run_id": self.run_id, "type": type, "agent": agent, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        for listener in self.listeners:
            listener(event)
        return event
