# Software factory: reference

How the factory works, how to configure it and its command line. For setup and the demo, see the
[main README](../README.md).

## How a run works

| # | Stage | Agent | What it does | Writes to the run state |
|---|---|---|---|---|
| 1 | Requirements | Requirements Agent | User stories and acceptance criteria | `title`, `user_stories`, `acceptance_criteria`, `out_of_scope` |
| 2 | Analysis | Codebase Analyst | Reads the store, maps the change to each tier, lists risks | `impact_analysis`, `affected_files` |
| 3 | Design | Architect Agent | API contract first, then the schema change and a build plan | `api_contract`, `schema_change`, `plan` |
| 4a | Build | DB Agent | Alembic migration, models, seed data | `db_changes` |
| 4b | Build | Backend Agent | FastAPI endpoints and pytest tests | `api_changes` |
| 4c | Build | Frontend Agent | React UI, Vitest tests and one Playwright journey | `ui_changes` |
| 5 | Test | QA Agent | Writes independent acceptance tests from the criteria; when a suite fails, diagnoses it and sends the work back to the right agent (max 3 loops) | `acceptance_tests`, `test_results`, `iteration`, `qa_history` |
| 6 | Review | Reviewer Agent | Reviews the full diff: security, contract consistency, quality | `review`, `verdict` |
| ⏸ | Approval | You | Approve or reject on the dashboard | `approved_by`, `approved_at` |
| 7 | Release | Release Agent + release tools | Writes the CHANGELOG entry; the tools back up the database, merge to `main`, migrate, rebuild the frontend, restart the API and tag the version | `version`, `release_notes` |

- Each agent is a separate **Claude Agent SDK** run with its own role prompt, tools, limits and output schema
  ([factory/agents/](factory/agents/), one file per agent).
- The run state is one JSON object per requirement: `runs/REQ-xxx/state.json`. Every step is also an event in
  `runs/REQ-xxx/events.jsonl`, which the dashboard streams live and demo mode replays.
- Before the build, the factory creates the branch `feature/REQ-xxx-<slug>` in its own worktree
  (`store/.worktrees/`), so the running store stays on `main` until you approve.
- The test suites are run by plain code ([factory/tools.py](factory/tools.py)), so the counts are exact. The release
  mechanics are plain code too. The agents decide *what* to change; the tools do the mechanical steps the same way
  every time.

## Safety

[factory/guard.py](factory/guard.py) is a `PreToolUse` hook that checks every tool call before it runs:

- reads only inside the store (or the feature worktree);
- edits only inside the agent's own folders (for example the DB Agent: `db/` and `api/models/`), and never QA's
  acceptance tests unless you are QA;
- shell commands only from the agent's allow-list (its test runner, `git diff` for the reviewer); no redirects,
  no network, no `git push`, no `rm`;
- no external connectors (MCP tools).

Agents run in `dontAsk` mode (anything not allowed is refused, never prompted), ignore your personal Claude Code
settings, and have per-agent turn and budget limits.

## factory.yaml

| Setting | Meaning |
|---|---|
| `store.path`, `store.main_branch` | Where the store repo is, and its release branch |
| `store.web_url`, `store.api_url` | The store's website ("View in store" links) and API (checked after a release) |
| `auth` | `subscription` (your Claude Code login) or `api_key` (`ANTHROPIC_API_KEY` from `.env`) |
| `model`, `effort` | The model every agent uses and how hard it thinks |
| `demo.enabled`, `demo.speed`, `demo.max_gap_seconds`, `demo.show_badge` | Demo mode (or start with `-Demo` / `DEMO_MODE=1`), playback speed, the longest pause kept, and whether the dashboard shows a "demo replay" badge |
| `limits.max_turns`, `limits.max_budget_usd` | Default limits per agent run (budget is API-equivalent dollars) |
| `qa.max_loops` | How many times QA may send work back before the run fails |
| `agents.<name>` | Per-agent limit overrides |

## Command line

Run from this folder with the factory's Python (`.\.venv\Scripts\python` on Windows, `.venv/bin/python` on Mac):

| Command | What it does |
|---|---|
| `python -m factory run "<requirement>"` | Runs a requirement up to the approval gate, printing progress |
| `python -m factory approve REQ-001 --by <name>` | Approves and releases |
| `python -m factory reject REQ-001 --by <name> --reason "..."` | Rejects; the branch is kept for reference |
| `python -m factory resume REQ-001` | Continues a failed run from the stage that stopped |
| `python -m factory status [REQ-001]` | Lists runs, or shows one |
| `python -m factory record REQ-001 --name <name> --keywords a,b` | Turns a released run into `demo/<name>.json` |
| `python -m factory recordings` / `checkpoints` | Lists recordings / checkpoints |
| `python -m factory save-checkpoint <name>` | Tags the store's `main` and snapshots the runs |
| `python -m factory reset-to <name>` | Restores the store, its database and the runs to a checkpoint |

The server ([server/app.py](server/app.py), started by `run-factory`) offers the same actions over REST, with
interactive docs at http://localhost:8000/docs, and the live event stream at `/api/events`.

## Folder map

```
software-factory/
  factory/            pipeline.py (stages, QA loop, gate, release), agents/ (one file per agent),
                      guard.py, tools.py, demo.py (checkpoints, recordings, replay), config.py, state.py, events.py
  server/             app.py (REST API), stream.py (live events), runner.py (background runs)
  dashboard/          index.html (single page, no build step)
  demo/               wishlist.json, discounts.json (recordings); checkpoints/ (runs snapshots)
  runs/               one folder per requirement (created as you go)
  factory.yaml        configuration
  tests/              the factory's own tests (python -m pytest)
```
