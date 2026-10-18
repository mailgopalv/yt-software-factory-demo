"""Starts factory runs as background processes and knows which run, if any, is active.

Each run is a separate `python -m factory ...` process, the same code as the command line.
A long release can't freeze the server, and a run carries on if the server restarts.
"""
import os
import subprocess
import sys

from factory import state as state_module
from factory.config import FACTORY_DIR
from factory.state import RunState, list_runs


class FactoryBusy(RuntimeError):
    """Only one run works on the store at a time (one repo, fixed test ports)."""

    def __init__(self, run_id: str):
        super().__init__(f"The factory is busy with {run_id}. Wait for it to finish or reach the approval gate.")
        self.run_id = run_id


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Runner:
    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}

    def active_run(self) -> str | None:
        """The id of the run currently working, or None."""
        for run_id, proc in self.processes.items():
            if proc.poll() is None:
                return run_id
        for run in list_runs():
            if run["status"] == "in_progress" and pid_alive(run.get("pid")):
                return run["id"]
        return None

    def launch(self, run_id: str, *args: str) -> None:
        """Runs `python -m factory <args>` in the background, logging to the run's console.log."""
        busy = self.active_run()
        if busy:
            raise FactoryBusy(busy)
        log = (state_module.RUNS_DIR / run_id / "console.log").open("a", encoding="utf-8")
        self.processes[run_id] = subprocess.Popen(
            [sys.executable, "-m", "factory", *args],
            cwd=FACTORY_DIR,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            # Its own process group, so stopping the server with Ctrl+C doesn't kill a run.
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )

    def mark_interrupted(self) -> None:
        """A run left 'in progress' by a process that no longer exists is marked failed, so it can be resumed."""
        for run in list_runs():
            if run["status"] != "in_progress" or pid_alive(run.get("pid")):
                continue
            proc = self.processes.get(run["id"])
            if proc and proc.poll() is None:
                continue
            state = RunState.load(run["id"])
            message = "Interrupted: the factory process stopped before the run finished."
            state.update(status="failed", error=message)
            state.log.emit("run_failed", error=message, usage_limit=False, resumable=not state.get("approved_at"))
