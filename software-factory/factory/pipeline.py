"""Runs a requirement through the SDLC: the stages in order, the QA loop and the approval gate.

  1 Requirements -> 2 Analysis -> 3 Design -> 4 Build (DB -> API -> UI) -> 5 QA -> 6 Review
  -> [human approval gate] -> 7 Release

`start()` runs up to the gate and stops with status "awaiting_approval". `approve()` runs the
release; `reject()` discards the change. Every step is written to the run's event log.
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from factory import demo, tools
from factory.agents import AGENTS, TIER_AGENTS
from factory.agents.base import UsageLimitReached, run_agent
from factory.agents.qa_agent import AUTHOR_SPEC
from factory.config import Config
from factory.events import Listener
from factory.state import RunState

STAGES = {
    "requirements": ("Requirements", ["requirements_agent"]),
    "analysis": ("Analysis", ["codebase_analyst"]),
    "design": ("Design", ["architect_agent"]),
    "build": ("Build", ["db_agent", "backend_agent", "frontend_agent"]),
    "qa": ("Test", ["qa_agent"]),
    "review": ("Review", ["reviewer_agent"]),
    "approval": ("Approval", []),
    "release": ("Release", ["release_agent"]),
}
TIERS = [("db", "db_agent", "db_changes"), ("api", "backend_agent", "api_changes"), ("ui", "frontend_agent", "ui_changes")]
SUITE_ORDER = ["api", "ui", "e2e"]


class PipelineError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, config: Config, listeners: list[Listener] | None = None):
        self.config = config
        self.listeners = listeners or []
        self.store = config.store_path

    # ---------- the run, up to the approval gate ----------

    def create_run(self, requirement: str) -> RunState:
        """Checks the factory is ready, then adds the requirement to the backlog as a new run."""
        self.preflight()
        recording = None
        if self.config.demo_enabled:
            try:
                recording = demo.choose_recording(requirement)
            except demo.DemoError as err:
                raise PipelineError(str(err)) from None
        state = RunState.create(requirement, self.listeners)
        if recording:
            state.update(demo_recording=recording["name"])
        state.log.emit("run_created", requirement=requirement)
        return state

    async def start(self, requirement: str) -> RunState:
        state = self.create_run(requirement)
        await self.to_gate(state)
        return state

    async def to_gate(self, state: RunState) -> None:
        """A real run, or in demo mode a replay of the chosen recording."""
        if not state.get("demo_recording"):
            await self.run_to_gate(state)
            return
        try:
            recording = demo.load_recording(state["demo_recording"])
            await demo.replay_to_gate(state, recording, self.config.demo_speed, self.config.demo_max_gap)
        except Exception as err:  # noqa: BLE001
            self.fail(state, err)

    async def execute(self, run_id: str) -> RunState:
        """Runs a requirement that is already in the backlog (the dashboard creates runs this way)."""
        state = RunState.load(run_id, self.listeners)
        if state["status"] != "new":
            raise PipelineError(f"{run_id} is {state['status']}, not new.")
        await self.to_gate(state)
        return state

    async def resume(self, run_id: str) -> RunState:
        """Continues a failed run from the stage that stopped (e.g. after a usage limit resets)."""
        state = RunState.load(run_id, self.listeners)
        if state["status"] != "failed":
            raise PipelineError(f"{run_id} is {state['status']}; only failed runs can be resumed.")
        if state.get("approved_at"):
            raise PipelineError(f"{run_id} failed during release. Check the store by hand before trying again.")
        if state.get("demo_recording"):
            raise PipelineError(f"{run_id} is a demo replay; start it again instead of resuming.")
        self.preflight()
        await self.run_to_gate(state)
        return state

    async def run_to_gate(self, state: RunState) -> None:
        """Runs every stage up to the approval gate, skipping stages a resumed run already finished."""
        log = state.log
        try:
            if "stages" not in state.data:
                state.update(status="in_progress", stages={name: "waiting" for name in STAGES}, started_at=now(),
                             auth=self.config.auth, model=self.config.model, pid=os.getpid())
                log.emit("run_started", requirement=state["requirement"], auth=self.config.auth, model=self.config.model,
                         stages=[{"id": k, "title": v[0], "agents": v[1]} for k, v in STAGES.items()])
            else:
                resume_from = next(name for name, status in state["stages"].items() if status != "done")
                state.update(status="in_progress", error=None, pid=os.getpid())
                log.emit("run_resumed", stage=resume_from)

            if not self.is_done(state, "requirements"):
                async with self.stage(state, "requirements"):
                    out = await self.agent("requirements_agent", state, self.store)
                    state.update("requirements_agent", **out)

            if not self.is_done(state, "analysis"):
                async with self.stage(state, "analysis"):
                    out = await self.agent("codebase_analyst", state, self.store)
                    state.update("codebase_analyst", **out)

            if not self.is_done(state, "design"):
                async with self.stage(state, "design"):
                    out = await self.agent("architect_agent", state, self.store)
                    state.update("architect_agent", **out)

            worktree = self.workspace(state) if self.is_done(state, "build") else None
            if not self.is_done(state, "build"):
                async with self.stage(state, "build"):
                    worktree = self.workspace(state)
                    if "baseline_tests" not in state.data:
                        baseline = await self.run_tests(state, worktree, "baseline")
                        state.update(baseline_tests=baseline)
                        if not all(r["ok"] for r in baseline.values()):
                            raise PipelineError("The store's tests fail before any change was made. Fix main first.")
                    for tier, agent_name, key in TIERS:
                        if key in state.data:
                            continue  # this tier was built before the run was resumed
                        log.emit("tier_started", agent_name, tier=tier)
                        out = await self.agent(agent_name, state, worktree)
                        state.update(agent_name, **out)
                        message = f"{state.id} {tier}: {state['title']}\n\n{out[key]['summary']}"
                        commit = tools.commit_all(worktree, message)
                        log.emit("tier_finished", agent_name, tier=tier, commit=commit)

            if not self.is_done(state, "qa"):
                async with self.stage(state, "qa"):
                    await self.qa_loop(state, worktree)

            if not self.is_done(state, "review"):
                async with self.stage(state, "review"):
                    changes = tools.diff(worktree, self.config.main_branch)
                    (state.run_dir / "diff.patch").write_text(changes["patch"], encoding="utf-8")
                    state.update(
                        files_changed=changes["files"],
                        migration_sql=tools.migration_sql(worktree, state["base_migration"]),
                    )
                    out = await self.agent("reviewer_agent", state, worktree, {
                        "files": changes["files"],
                        "test_summary": test_summary(state["test_results"], state["baseline_tests"]),
                    })
                    state.update("reviewer_agent", **out)

            self.set_stage(state, "approval", "active")
            state.update(status="awaiting_approval")
            log.emit("gate_waiting", verdict=state["verdict"], tests=test_summary(state["test_results"], state["baseline_tests"]),
                     files=len(state["files_changed"]), cost_usd=state.get("cost_usd", 0))
        except Exception as err:  # noqa: BLE001 (any failure ends the run and is reported)
            self.fail(state, err)

    def preflight(self) -> None:
        if self.config.demo_enabled:
            pass  # replays don't call Claude, so no login or key is needed
        elif self.config.auth == "api_key":
            if not self.config.api_key:
                raise PipelineError("auth is api_key but there is no ANTHROPIC_API_KEY. Copy .env.example to .env and add your key.")
        elif not tools.claude_login_status().get("loggedIn"):
            raise PipelineError("Not logged in to Claude Code. Run `claude`, type /login, then try again.")
        if not (self.store / ".git").exists():
            raise PipelineError(f"{self.store} is not a git repo. Check store.path in factory.yaml.")
        if tools.git(self.store, "branch", "--show-current") != self.config.main_branch:
            raise PipelineError(f"The store must be on the {self.config.main_branch} branch.")
        if not tools.store_is_clean(self.store):
            raise PipelineError("The store has uncommitted changes. Commit or discard them first.")

    def workspace(self, state: RunState) -> Path:
        """The feature branch's worktree: created on first use, re-attached when a run is resumed."""
        if state.get("branch"):
            return tools.attach_worktree(self.store, state["branch"])
        branch = f"feature/{state.id}-{tools.slugify(state['title'])}"
        worktree = tools.create_worktree(self.store, branch, self.config.main_branch)
        state.update(branch=branch, worktree=str(worktree), base_migration=tools.migration_head(worktree),
                     base_commit=tools.git(worktree, "rev-parse", "--short", "HEAD"))
        state.log.emit("branch_created", branch=branch, path=str(worktree))
        return worktree

    @staticmethod
    def is_done(state: RunState, stage: str) -> bool:
        return state.get("stages", {}).get(stage) == "done"

    async def qa_loop(self, state: RunState, worktree: Path) -> None:
        """Runs every suite; on failure QA sends the work back to the tier at fault (max N loops)."""
        log = state.log
        loops = state.get("iteration", 0)  # a resumed run keeps its loop count
        if "qa_history" not in state.data:
            state.update(iteration=0, qa_history=[])
        if "acceptance_tests" not in state.data:
            # QA writes independent acceptance tests from the criteria before the full test run.
            log.emit("tier_started", "qa_agent", tier="qa")
            out = await run_agent(AUTHOR_SPEC.for_run(state), state, self.config, worktree)
            state.update("qa_agent", **out)
            message = f"{state.id} qa: {state['title']} acceptance tests\n\n{out['acceptance_tests']['summary']}"
            log.emit("tier_finished", "qa_agent", tier="qa", commit=tools.commit_all(worktree, message))
        while True:
            results = await self.run_tests(state, worktree, f"qa-{loops}")
            state.update("qa_agent", test_results=results)
            failing = [r for r in results.values() if not r["ok"]]
            if not failing:
                log.emit("qa_passed", "qa_agent", loops=loops)
                return
            if loops >= self.config.qa_max_loops:
                raise PipelineError(f"Tests still failing after {loops} QA loops: " + ", ".join(r["name"] for r in failing))

            loops += 1
            state.update(iteration=loops)
            failure_output = self.failure_output(state, failing, f"qa-{loops - 1}")
            diagnosis = await self.agent("qa_agent", state, worktree, {"iteration": loops, "failure_output": failure_output})
            agent_name = TIER_AGENTS[diagnosis["tier"]]
            state.update("qa_agent", qa_history=state["qa_history"] + [{"loop": loops, "failing": [r["tier"] for r in failing], **diagnosis}])
            log.emit("qa_sendback", "qa_agent", loop=loops, tier=diagnosis["tier"], to_agent=agent_name, diagnosis=diagnosis["diagnosis"])

            if diagnosis["tier"] == "qa":
                spec, key = AUTHOR_SPEC.for_run(state), "acceptance_tests"
            else:
                spec, key = AGENTS[agent_name], next(k for t, a, k in TIERS if a == agent_name)
            out = await run_agent(spec, state, self.config, worktree, {
                "iteration": loops,
                "qa_feedback": f"{diagnosis['diagnosis']}\n\nWhat to fix: {diagnosis['fix_instructions']}",
                "failure_output": failure_output,
            })
            state.update(agent_name, **{key: out[key]})
            commit = tools.commit_all(worktree, f"{state.id} {diagnosis['tier']}: fix from QA loop {loops}")
            log.emit("tier_finished", agent_name, tier=diagnosis["tier"], commit=commit, loop=loops)

    async def run_tests(self, state: RunState, workspace: Path, label: str) -> dict:
        log = state.log
        out_dir = state.run_dir / "tests"
        results = {}
        for tier in SUITE_ORDER:
            log.emit("tests_started", tier=tier, name=tools.SUITES[tier], label=label)
            result = await tools.run_suite(tier, workspace, out_dir, lambda line, t=tier: log.emit("test_output", tier=t, line=line))
            (out_dir / f"{label}-{tier}.log").write_text(result.pop("output_tail"), encoding="utf-8")
            results[tier] = result
            log.emit("tests_finished", label=label, **result)  # result includes the tier
        return results

    @staticmethod
    def failure_output(state: RunState, failing: list[dict], label: str) -> str:
        parts = []
        for r in failing:
            tail = (state.run_dir / "tests" / f"{label}-{r['tier']}.log").read_text(encoding="utf-8")
            parts.append(f"### {r['name']}: {r['failed']} failed, {r['passed']} passed\n{tail[-6000:]}")
        return "\n\n".join(parts)

    # ---------- the human gate ----------

    async def approve(self, run_id: str, approved_by: str) -> RunState:
        state = RunState.load(run_id, self.listeners)
        if state["status"] != "awaiting_approval":
            raise PipelineError(f"{run_id} is {state['status']}, not awaiting approval.")
        state.update(approved_by=approved_by, approved_at=now(), status="in_progress", pid=os.getpid())
        state.log.emit("approved", by=approved_by)
        if state.get("demo_recording"):
            # The recording's own events mark the gate done and replay the release; the store change is real.
            try:
                recording = demo.load_recording(state["demo_recording"])
                await demo.replay_release(self.config, state, recording, approved_by, self.config.demo_speed, self.config.demo_max_gap)
            except Exception as err:  # noqa: BLE001
                self.fail(state, err)
            return state
        self.set_stage(state, "approval", "done")
        try:
            async with self.stage(state, "release"):
                await self.release(state)
        except Exception as err:  # noqa: BLE001
            self.fail(state, err)
        return state

    def reject(self, run_id: str, rejected_by: str, reason: str = "") -> RunState:
        state = RunState.load(run_id, self.listeners)
        if state["status"] not in ("awaiting_approval", "failed"):
            raise PipelineError(f"{run_id} is {state['status']}; only runs awaiting approval or failed can be rejected.")
        if state["status"] == "awaiting_approval":
            self.set_stage(state, "approval", "failed")
        if state.get("worktree"):
            tools.remove_worktree(self.store, Path(state["worktree"]))
        state.update(status="rejected", rejected_by=rejected_by, rejected_at=now(), rejection_reason=reason)
        state.log.emit("rejected", by=rejected_by, reason=reason, branch_kept=state.get("branch"))
        return state

    # ---------- release ----------

    async def release(self, state: RunState) -> None:
        log = state.log
        worktree = Path(state["worktree"])
        old_version = tools.read_version(worktree)
        version = tools.next_minor_version(old_version)

        def step(name: str, detail: str = "") -> None:
            log.emit("release_step", "release_agent", step=name, detail=detail)

        out = await self.agent("release_agent", state, worktree, {"version": version, "date": datetime.now().strftime("%Y-%m-%d")})
        tools.write_version(worktree, version)
        tools.commit_all(worktree, f"Release v{version}: {state['title']} ({state.id})")
        step("Version bumped", f"{old_version} -> {version}, CHANGELOG updated")

        if not tools.store_is_clean(self.store):
            raise PipelineError("The live store has uncommitted changes; refusing to merge.")
        backup = tools.backup_db(self.store, f"v{version}")
        step("Database backed up", str(backup.relative_to(self.store)) if backup else "no database yet")
        commit = tools.merge_to_main(self.store, state["branch"], f"Merge {state.id}: {state['title']} (approved by {state['approved_by']})")
        step("Merged to main", f"{state['branch']} -> {self.config.main_branch} ({commit})")
        step("Migration run", tools.migrate_live_db(self.store))
        tools.build_frontend(self.store)
        step("Frontend rebuilt", "npm run build passed")
        step("API restarted", tools.reload_api(self.store, self.config.api_url, version))
        tools.tag(self.store, f"v{version}", f"{state['title']} ({state.id})")
        step("Tagged", f"v{version}")
        tools.remove_worktree(self.store, worktree)

        state.update("release_agent", version=version, release_notes=out["release_notes"], highlights=out["highlights"],
                     release_commit=commit, released_at=now(), status="released")
        log.emit("released", version=version, title=state["title"], files=len(state.get("files_changed", [])))

    # ---------- helpers ----------

    async def agent(self, name: str, state: RunState, workspace: Path, extra: dict | None = None) -> dict:
        return await run_agent(AGENTS[name], state, self.config, workspace, extra)

    @asynccontextmanager
    async def stage(self, state: RunState, name: str):
        self.set_stage(state, name, "active")
        try:
            yield
        except Exception:
            self.set_stage(state, name, "failed")
            raise
        self.set_stage(state, name, "done")

    @staticmethod
    def set_stage(state: RunState, name: str, status: str) -> None:
        stages = dict(state.get("stages", {}))
        stages[name] = status
        state.data["stages"] = stages
        state.save()
        title, agents = STAGES[name]
        state.log.emit("stage", stage=name, title=title, status=status, agents=agents)

    @staticmethod
    def fail(state: RunState, err: Exception) -> None:
        resumable = not state.get("approved_at")
        state.update(status="failed", error=str(err), failed_at=now())
        state.log.emit("run_failed", error=str(err), usage_limit=isinstance(err, UsageLimitReached), resumable=resumable)


def test_summary(results: dict, baseline: dict | None = None) -> str:
    """e.g. 'API (pytest) 17->22 ok, UI (Vitest) 10->13 ok, E2E (Playwright) 4->4 ok'"""
    parts = []
    for tier, r in results.items():
        before = f"{baseline[tier]['passed']}->" if baseline and tier in baseline else ""
        parts.append(f"{r['name']} {before}{r['passed']} {'ok' if r['ok'] else 'FAILED'}")
    return ", ".join(parts)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
