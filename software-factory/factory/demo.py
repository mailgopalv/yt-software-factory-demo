"""Checkpoints, recordings and demo mode.

Checkpoints: git tags in the store plus a snapshot of the factory's runs, so any video scene can be
re-shot from a known state (`reset-to`).

Recordings: a released run saved as demo/<name>.json (its events with timings, its diff, and the
release commit). In demo mode the factory replays a recording instead of calling Claude: the dashboard
sees exactly the same events. Approving a replay really releases the recorded code into the store, so
refreshing the store shows the feature.
"""
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from factory import state as state_module
from factory import tools
from factory.config import FACTORY_DIR, Config
from factory.state import RunState

DEMO_DIR = FACTORY_DIR / "demo"
SNAPSHOTS = DEMO_DIR / "checkpoints"
ARCHIVE = FACTORY_DIR / "runs-archive"

CHECKPOINTS = {
    "checkpoint-1-store-only": "The store on its own",
    "checkpoint-2-factory-added": "Factory configured (store code unchanged)",
    "checkpoint-3-wishlist": "After Demo 1: wishlist released",
    "checkpoint-4-discounts": "After Demo 2: discount codes released",
}
SKIP_ON_REPLAY = {"run_created", "agent_log"}
RUN_SPECIFIC_KEYS = {"pid", "worktree"}


class DemoError(RuntimeError):
    pass


# ---------- checkpoints ----------

def save_checkpoint(config: Config, name: str) -> str:
    """Tags the store's current main as a checkpoint and snapshots the factory's runs."""
    store = config.store_path
    if tools.git(store, "branch", "--show-current") != config.main_branch or not tools.store_is_clean(store):
        raise DemoError(f"The store must be on a clean {config.main_branch} branch to save a checkpoint.")
    tools.git(store, "tag", "-f", "-a", name, "-m", CHECKPOINTS.get(name, name))
    target = SNAPSHOTS / name / "runs"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for run_dir in sorted(state_module.RUNS_DIR.glob("REQ-*")):
        shutil.copytree(run_dir, target / run_dir.name, ignore=shutil.ignore_patterns("tests", "console.log"))
    return tools.git(store, "rev-parse", "--short", name)


def reset_to(config: Config, name: str, say=print) -> None:
    """Restores the store code, a fresh database and the dashboard's runs to a checkpoint."""
    store = config.store_path
    if not tools.git(store, "tag", "--list", name):
        raise DemoError(f"No checkpoint called {name}. Saved checkpoints: {', '.join(list_checkpoints(config)) or 'none'}")
    busy = [r["id"] for r in state_module.list_runs() if r["status"] == "in_progress"]
    if busy:
        raise DemoError(f"{', '.join(busy)} is still in progress. Wait for it, or reject it, before resetting.")

    for worktree in (store / ".worktrees").glob("*") if (store / ".worktrees").exists() else []:
        tools.remove_worktree(store, worktree)
    tools.git(store, "checkout", "-q", config.main_branch)
    tools.git(store, "reset", "-q", "--hard", f"{name}^{{commit}}")
    say(f"Store code reset to {name} ({tools.git(store, 'rev-parse', '--short', 'HEAD')}), version {tools.read_version(store)}")

    # Feature branches and release tags from later in the story would clash with new runs.
    for branch in tools.git(store, "for-each-ref", "--format=%(refname:short)", "refs/heads/feature/").split():
        if not is_ancestor(store, branch, "HEAD"):
            tools.git(store, "branch", "-q", "-D", branch)
    for tag in tools.git(store, "tag", "--list", "v*").split():
        if not is_ancestor(store, tag, "HEAD"):
            tools.git(store, "tag", "-d", tag)

    rebuild_database(store)
    say("Database rebuilt from this checkpoint's migrations and seed data")
    os.utime(store / "api" / "main.py")  # the store API (run with --reload) restarts and reports the version

    archived = archive_runs(f"before-{name}")
    snapshot = SNAPSHOTS / name / "runs"
    state_module.RUNS_DIR.mkdir(exist_ok=True)
    if snapshot.exists():
        for run_dir in snapshot.iterdir():
            shutil.copytree(run_dir, state_module.RUNS_DIR / run_dir.name)
    restored = len(list(state_module.RUNS_DIR.glob("REQ-*")))
    say(f"Factory runs: {restored} restored for this checkpoint" + (f"; previous runs archived to {archived}" if archived else ""))


def list_checkpoints(config: Config) -> list[str]:
    return tools.git(config.store_path, "tag", "--list", "checkpoint-*").split()


def is_ancestor(store: Path, ref: str, of: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", ref, of], cwd=store, capture_output=True).returncode == 0


def rebuild_database(store: Path) -> None:
    """Empties store.db and rebuilds it with this checkpoint's migrations and seed data.

    The tables are dropped instead of deleting the file, because the running store API keeps it open
    (Windows won't delete an open file) and a newer checkpoint's migration history may be gone."""
    db = store / "db" / "store.db"
    if db.exists():
        with sqlite3.connect(db) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            names = conn.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            for kind, obj in names:
                if kind == "table":
                    conn.execute(f'DROP TABLE IF EXISTS "{obj}"')
            conn.commit()
    python = tools.store_python(store)
    tools.run([python, "-m", "alembic", "-c", "db/alembic.ini", "upgrade", "head"], store)
    tools.run([python, "-m", "db.seed"], store)


def archive_runs(label: str) -> Path | None:
    runs = sorted(state_module.RUNS_DIR.glob("REQ-*")) if state_module.RUNS_DIR.exists() else []
    if not runs:
        return None
    target = ARCHIVE / f"{datetime.now():%Y%m%d-%H%M%S}-{label}"
    target.mkdir(parents=True)
    for run_dir in runs:
        shutil.move(str(run_dir), target / run_dir.name)
    return target


# ---------- recordings ----------

def record(config: Config, run_id: str, name: str, keywords: list[str]) -> Path:
    """Turns a released run into demo/<name>.json."""
    state = RunState.load(run_id)
    if state["status"] != "released":
        raise DemoError(f"{run_id} is {state['status']}. Only released runs can become recordings.")
    events = [json.loads(line) for line in (state.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    events = without_interruptions([e for e in events if e["type"] not in SKIP_ON_REPLAY | {"usage_limit"}])
    gate = next(i for i, e in enumerate(events) if e["type"] == "gate_waiting")
    approved = next(i for i, e in enumerate(events) if e["type"] == "approved")
    start = events[0]["ts"]

    def timed(items):
        return [{**e, "t": round(e.pop("ts") - start, 3)} for e in (dict(x) for x in items)]

    recording = {
        "name": name,
        "title": state["title"],
        "requirement": state["requirement"],
        "keywords": [k.lower() for k in keywords],
        "source_run": run_id,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "model": state.get("model"),
        "diff": (state.run_dir / "diff.patch").read_text(encoding="utf-8"),
        "release": {"commit": tools.git(config.store_path, "rev-parse", state["release_commit"]), "version": state["version"]},
        "events_to_gate": timed(events[: gate + 1]),
        "events_release": timed(events[approved + 1:]),
    }
    DEMO_DIR.mkdir(exist_ok=True)
    path = DEMO_DIR / f"{name}.json"
    path.write_text(json.dumps(recording, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def without_interruptions(events: list[dict]) -> list[dict]:
    """Cuts out attempts that stopped and were resumed (e.g. a usage limit), so a recording plays as one
    continuous run: from the start of the interrupted stage up to and including the resume."""
    events = list(events)
    while True:
        resumed = next((i for i, e in enumerate(events) if e["type"] == "run_resumed"), None)
        if resumed is None:
            return events
        failed = max(i for i, e in enumerate(events[:resumed]) if e["type"] == "run_failed")
        failed_stage = next((e["stage"] for e in reversed(events[:failed]) if e["type"] == "stage" and e["status"] == "failed"), None)
        start = max((i for i, e in enumerate(events[:failed])
                     if e["type"] == "stage" and e["stage"] == failed_stage and e["status"] == "active"), default=failed)
        events = events[:start] + events[resumed + 1:]


def recordings() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DEMO_DIR.glob("*.json"))]


def choose_recording(requirement: str) -> dict:
    """Picks the recording whose keywords best match the typed requirement."""
    text = requirement.lower()
    scored = [(sum(k in text for k in r["keywords"]), r) for r in recordings()]
    scored = [(score, r) for score, r in scored if score > 0]
    if not scored:
        names = ", ".join(f"{r['name']} ({'/'.join(r['keywords'])})" for r in recordings()) or "none recorded yet"
        raise DemoError(f"Demo mode: no recording matches that requirement. Recordings: {names}")
    return max(scored, key=lambda pair: pair[0])[1]


def load_recording(name: str) -> dict:
    path = DEMO_DIR / f"{name}.json"
    if not path.exists():
        raise DemoError(f"No recording called {name} in {DEMO_DIR}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- replay ----------

def for_this_run(items: list[dict], source_run: str, run_id: str) -> list[dict]:
    """Recorded events mention the original run id (branch names, file paths); swap in the new one."""
    return json.loads(json.dumps(items).replace(source_run, run_id))


async def play(state: RunState, events: list[dict], speed: float, max_gap: float, on_event=None) -> None:
    """Writes recorded events into the run with their original rhythm (sped up, long pauses shortened)."""
    previous = events[0]["t"] if events else 0
    for e in events:
        await asyncio.sleep(min(max_gap, max(0.0, (e["t"] - previous) / speed)))
        previous = e["t"]
        if on_event and on_event(e):
            continue
        apply(state, e)


def apply(state: RunState, e: dict) -> None:
    kind, agent = e["type"], e.get("agent")
    data = {k: v for k, v in e.items() if k not in ("t", "ts", "run_id", "type", "agent")}
    if kind == "state_updated":
        values = {k: v for k, v in (e.get("values") or {}).items() if k not in RUN_SPECIFIC_KEYS}
        if values:
            state.update(agent, **values)
    elif kind == "stage":
        state.data.setdefault("stages", {})[e["stage"]] = e["status"]
        state.save()
        state.log.emit("stage", agent, **data)
    else:
        state.log.emit(kind, agent, **data)


def feature_commits(store: Path, release_commit: str) -> list[str]:
    """The recorded feature branch's commits, oldest first: one per tier commit, then the release commit.

    The release commit is the merge into main, so its second parent is the tip of the feature branch."""
    return tools.git(store, "rev-list", "--reverse", f"{release_commit}^1..{release_commit}^2").split()


async def replay_to_gate(state: RunState, recording: dict, speed: float, max_gap: float,
                         store: Path | None = None, main_branch: str = "main") -> None:
    """Replays a run up to the gate. With a store, the feature branch is real too: its worktree is created
    when the branch was, and moves to the recorded code at each tier commit."""
    state.update(pid=os.getpid(), demo_recording=recording["name"])
    (state.run_dir / "diff.patch").write_text(recording["diff"].replace(recording["source_run"], state.id), encoding="utf-8")
    events = for_this_run(recording["events_to_gate"], recording["source_run"], state.id)
    commits = []
    if store:
        release = recording["release"]["commit"]
        if not is_ancestor(store, "HEAD", release):
            raise DemoError(f"The store isn't at the checkpoint this recording starts from. Reset it first "
                            f"(the recording releases v{recording['release']['version']}).")
        commits = feature_commits(store, release)[:-1]  # the release commit is checked out at approval

    def real_step(e: dict) -> bool:
        """Creates the worktree and moves the branch at the recorded moments, reporting the real values."""
        if not store or e["type"] not in ("branch_created", "tier_finished"):
            return False
        data = {k: v for k, v in e.items() if k not in ("t", "ts", "run_id", "type", "agent")}
        if e["type"] == "branch_created":
            worktree = tools.create_worktree(store, e["branch"], main_branch)
            state.update(worktree=str(worktree), base_commit=tools.git(worktree, "rev-parse", "--short", "HEAD"))
            data["path"] = str(worktree)
        elif commits and state.get("worktree"):
            worktree = Path(state["worktree"])
            tools.git(worktree, "reset", "-q", "--hard", commits.pop(0))
            data["commit"] = tools.git(worktree, "rev-parse", "--short", "HEAD")
        else:
            return False
        state.log.emit(e["type"], e.get("agent"), **data)
        return True

    await play(state, events, speed, max_gap, on_event=real_step)


async def replay_release(config: Config, state: RunState, recording: dict, approved_by: str, speed: float, max_gap: float) -> None:
    """Replays the release, doing the real release steps on the store at the recorded moments."""
    store = config.store_path
    release = recording["release"]
    commit, version = release["commit"], release["version"]
    if not tools.store_is_clean(store):
        raise DemoError("The live store has uncommitted changes; refusing to release.")
    if not is_ancestor(store, "HEAD", commit):
        raise DemoError(f"The store isn't at the checkpoint this recording starts from. Reset it first "
                        f"(the recording releases v{version}).")
    worktree = Path(state["worktree"]) if state.get("worktree") and Path(state["worktree"]).exists() else None

    def real_step(e: dict) -> bool:
        """At each recorded release step, do the real thing to the store instead and report what happened."""
        if e["type"] != "release_step":
            return False
        step = e["step"]
        if step == "Version bumped" and worktree:
            tools.git(worktree, "reset", "-q", "--hard", f"{commit}^2")  # the recorded release commit
            detail = e.get("detail", "")
        elif step == "Database backed up":
            backup = tools.backup_db(store, f"v{version}")
            detail = str(backup.relative_to(store)) if backup else "no database yet"
        elif step == "Merged to main":
            tools.git(store, "merge", "-q", "--ff-only", commit)
            detail = f"{state.get('branch')} -> {config.main_branch} ({tools.git(store, 'rev-parse', '--short', 'HEAD')})"
        elif step == "Migration run":
            detail = tools.migrate_live_db(store)
        elif step == "Frontend rebuilt":
            tools.build_frontend(store)
            detail = "npm run build passed"
        elif step == "API restarted":
            detail = tools.reload_api(store, config.api_url, version)
        elif step == "Tagged":
            tools.git(store, *tools.FACTORY_AUTHOR, "tag", "-f", "-a", f"v{version}", commit, "-m", f"{state['title']} ({state.id})")
            detail = f"v{version}"
        else:
            return False
        state.log.emit("release_step", e.get("agent"), step=step, detail=detail)
        return True

    events = for_this_run(recording["events_release"], recording["source_run"], state.id)
    await play(state, events, speed, max_gap, on_event=real_step)
    if worktree:
        tools.remove_worktree(store, worktree)  # as a real release does; the branch is kept
    state.update(status="released", released_at=datetime.now().astimezone().isoformat(timespec="seconds"))
