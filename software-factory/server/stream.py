"""The live event stream (Server-Sent Events).

The server follows each run's events.jsonl file and sends every new line to the browser.
Because it reads the files, runs started from the command line show up live too, and demo
replays (which write the same files) look exactly like real runs.
"""
import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from factory import state as state_module

HIDDEN_EVENTS = {"agent_log"}   # internal Claude Code chatter, kept in the file but not streamed
POLL_SECONDS = 0.3
KEEP_ALIVE_SECONDS = 15


def event_files(run_id: str | None) -> list[Path]:
    runs_dir = state_module.RUNS_DIR
    if run_id:
        path = runs_dir / run_id / "events.jsonl"
        return [path] if path.exists() else []
    return sorted(runs_dir.glob("REQ-*/events.jsonl")) if runs_dir.exists() else []


def read_new_lines(path: Path, offset: int) -> tuple[list[str], int]:
    """Returns complete lines written after `offset`, and the new offset."""
    size = path.stat().st_size
    if size <= offset:
        return [], offset
    with path.open("rb") as f:
        f.seek(offset)
        chunk = f.read(size - offset)
    end = chunk.rfind(b"\n")
    if end == -1:
        return [], offset  # a line is still being written
    complete = chunk[: end + 1]
    return complete.decode("utf-8").splitlines(), offset + len(complete)


def visible(line: str) -> bool:
    try:
        return json.loads(line).get("type") not in HIDDEN_EVENTS
    except json.JSONDecodeError:
        return False


async def event_stream(is_disconnected: Callable, run_id: str | None = None, replay: bool = False) -> AsyncIterator[str]:
    """Yields SSE messages: every event appended to the runs' event logs from now on (or from the start with replay)."""
    offsets = {path: (0 if replay else path.stat().st_size) for path in event_files(run_id)}
    yield "retry: 2000\n\n"
    last_sent = time.time()
    while not await is_disconnected():
        for path in event_files(run_id):
            lines, offsets[path] = read_new_lines(path, offsets.get(path, 0))  # a new run's file starts at 0
            for line in lines:
                if visible(line):
                    yield f"data: {line}\n\n"
                    last_sent = time.time()
        if time.time() - last_sent > KEEP_ALIVE_SECONDS:
            yield ": keep-alive\n\n"
            last_sent = time.time()
        await asyncio.sleep(POLL_SECONDS)
