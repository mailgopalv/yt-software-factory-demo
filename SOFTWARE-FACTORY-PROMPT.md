# Build a software factory for your product

A reusable prompt for creating an **AI software factory** like the one in this repo, for **your own** product:
a team of Claude agents that takes a one-line requirement through requirements, analysis, design, build, test,
review, **your approval** and release, with a live dashboard.

It is written for a simple three-tier web app (a database, an API and a web frontend) that already has tests.

## How to use it

1. Open your product's repo in an editor with [Claude Code](https://claude.com/claude-code).
2. Fill in the **About my product** section below (or leave blanks and Claude will ask).
3. Paste everything from **"The prompt"** onwards into Claude Code.
4. Claude builds the factory one step at a time and stops after each step for you to try it. Say "next" to continue.

Tweak anything: the agents, the stages, the dashboard. This is a starting point, not a rulebook.

---

## The prompt

You are going to build an **AI software factory** for the product in this repository. Read this whole brief before
doing anything.

### About my product (fill in, or ask me)

| Question | My answer |
|---|---|
| Product folder (the repo the factory will change) | |
| Database tier: technology and folders (models, migrations, seed data) | |
| API tier: technology and folders (routes, schemas, API tests) | |
| UI tier: technology and folders (components, pages, UI tests) | |
| End-to-end tests, if any (tool and folder) | |
| Command to run each test suite | |
| Command to start the product locally, and its ports | |
| How the API picks up code changes (auto-reload? restart?) | |
| Main branch name | |
| My operating system (Windows / Mac / Linux) | |

If anything is blank, **ask me before writing code**. Then read the product's code and confirm back to me, in a short
table, which folders belong to which tier and which commands run which tests.

### How to work with me

- Build **one step at a time** (see Build order). After each step: stop, summarise in plain language what you built
  and exactly what I should run to try it, and wait for me to say "next".
- If something in this brief turns out to be wrong or impossible for my product, tell me and propose a fix.
  Don't silently change the plan.
- Don't change my product's own code to make the factory work, unless you've asked me first.
- Every step is done when: it runs, its tests pass, and you've told me exactly what to run.

### What to build

**Stack for the factory** (unless I say otherwise):

| Part | Choice |
|---|---|
| Agents | **Claude Agent SDK (Python)**. Check the current docs for the exact API before writing agent code |
| Factory server | Python + FastAPI, live progress with Server-Sent Events |
| Dashboard | One HTML page served by the factory server, no build step |
| Storage | Plain files: one folder per requirement with `state.json` and `events.jsonl` |
| Config | One `factory.yaml` (product path, model, login mode, limits) |
| Git | Local only. No pushing. All work happens on a feature branch until I approve |

Put the factory in its own folder next to my product (for example `software-factory/`), not inside it.

**The pipeline: one agent per stage, each a separate Claude Agent SDK run**

| # | Stage | Agent | Job | Writes to the run state |
|---|---|---|---|---|
| 1 | Requirements | Requirements agent | 2–4 user stories, 4–8 testable acceptance criteria (Given/When/Then), out-of-scope list | `title`, `user_stories`, `acceptance_criteria`, `out_of_scope` |
| 2 | Analysis | Codebase analyst | Read the product, map the change to each tier, name the patterns to copy and the risks | `impact_analysis`, `affected_files` |
| 3 | Design | Architect | API contract first (endpoints, requests, responses, status codes), then the database change and a build plan per tier | `api_contract`, `schema_change`, `plan` |
| 4a | Build | Database agent | Migration, models, seed data | `db_changes` |
| 4b | Build | Backend agent | Endpoints + API tests | `api_changes` |
| 4c | Build | Frontend agent | UI + UI tests + one end-to-end journey | `ui_changes` |
| 5 | Test | QA agent | First write independent acceptance tests from the acceptance criteria (the developer agents may not edit them). Then the factory runs every suite. On failure, QA diagnoses which tier is at fault and the work goes back to that agent (max 3 loops) | `acceptance_tests`, `test_results`, `iteration` |
| 6 | Review | Reviewer | Review the full diff: security (injection, input validation, data leaking between users), consistency with the API contract, quality | `review`, `verdict` |
| ⏸ | Approval | **Me** | Approve or reject on the dashboard, after seeing the tests, review, diff and migration SQL | `approved_by`, `approved_at` |
| 7 | Release | Release agent + release tools | The agent writes the changelog entry and release notes. Plain code does the rest: back up the database, merge to main, run the migration and seed, rebuild, restart the API, bump the version, tag | `version`, `release_notes` |

Rules:
- Each agent has its own **role prompt**, its own **tool list**, a **JSON output schema** (use the SDK's structured
  output), and **turn and budget limits**. One file per agent.
- Agents pass work forward through a shared **run state** (`runs/<id>/state.json`). Each agent adds its own keys.
- Build tiers **in order** (database → API → UI), committing after each.
- **The live product must not change until I approve.** Create the feature branch in a separate **git worktree**
  (inside the product repo, git-ignored) and let the agents work there. My running app stays on main.
- **Plain code, not AI, for the mechanical steps:** run the test suites and read pass/fail counts from each runner's
  machine-readable report (JUnit XML, JSON reporters), and do the release steps. The agents decide *what* to change.

**Safety: a guard on every tool call**

Use a `PreToolUse` hook that checks every tool call before it runs, and deny with a clear reason so the agent can
correct itself:
- reads only inside the product (or the feature worktree);
- edits only in the folders of that agent's own tier (read-only agents edit nothing; the release agent edits only the
  changelog); QA's acceptance test files are protected from the developer agents;
- shell commands only from a per-agent allow-list (its test command, `git diff`/`log`/`show` for the reviewer);
  no redirects, command substitution, background jobs, network tools, `rm`, or `git push`;
- no MCP / external connector tools.

Also run agents with permission mode `dontAsk` (refuse anything not allowed instead of prompting), an explicit tool
list, and `setting_sources=[]` so my personal Claude Code settings and CLAUDE.md files don't leak in. Write tests for
the guard.

**Login**

Support two modes in `factory.yaml`: `subscription` (the agents use my Claude Code login) and `api_key`
(`ANTHROPIC_API_KEY` from a git-ignored `.env`). Check Anthropic's current terms for the Agent SDK and my plan, and
tell me if anything there affects how I should run it.

**Dashboard (dark theme, readable at 1920×1080, also usable at half-screen width)**

- A requirement box and a backlog with statuses: new / in progress / awaiting approval / released / rejected / failed.
- A pipeline of stage cards (waiting / active / done / failed) with the active agent clearly highlighted;
  during the build, three tier lanes; a QA loop counter.
- A live activity feed: who is speaking, tool calls, guard blocks, test results.
- Tabs: user stories, run state (keys appear as agents write them), changes (impact analysis, API contract,
  migration SQL preview, red/green diff, tests per tier before → after), review.
- A big test counter, and approve / reject buttons at the gate.
- A release history with the version and a link to the running product.

**Server**

REST endpoints to add a requirement, list and read runs, read events and the diff, approve, reject and resume,
plus a live event stream. Run each requirement as its own background process (so a long release can't freeze the
server), one at a time. Stream events by following each run's `events.jsonl`, so runs started from the command line
also show up live.

**Command line**

`run "<requirement>"`, `approve <id>`, `reject <id>`, `resume <id>`, `status [id]`.

### Lessons learned (avoid these traps)

These all happened while building the original factory:

1. **External connectors bloat every agent.** With a Claude subscription login, Claude Code may load your claude.ai
   connectors (Drive, Docs…) into every agent session, adding ~140k tokens per agent. Turn them off for agents:
   `strict_mcp_config=True`, `mcp_servers={}`, `disallowed_tools=["mcp__*"]` and the environment variable
   `ENABLE_CLAUDEAI_MCP_SERVERS=false`. Measure an agent's token usage once to confirm.
2. **An API key in the environment silently wins over the subscription login.** In subscription mode, remove
   `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` from the agents' environment.
3. **Usage limits hit mid-run.** Detect the SDK's rate-limit events, stop cleanly with a plain message and the reset
   time, and support `resume` from the stage that stopped (skip stages already done).
4. **Shared installs in the worktree.** A fresh worktree has no virtualenv or `node_modules`. Link them from the main
   checkout (junctions on Windows, symlinks elsewhere), and **unlink before removing the worktree**, or the removal
   can delete the real installs.
5. **Auto-reload may silently not happen.** After a release, check the API really serves the new version (for example
   a health endpoint returning the version). On Windows, `uvicorn --reload` can hang; a tiny watcher script that
   restarts the API process directly is more reliable.
6. **Migrations don't add seed data.** After `migrate`, run the product's seed step if it only fills empty tables,
   or new reference data (codes, categories) is missing in the live database.
7. **Concurrent reads of state files.** The server can read `state.json` while a run is writing it. Write atomically
   (temp file + rename) and retry reads briefly.
8. **Agents try shell commands for reading** (`ls`, `cat`, `tail`). Deny them with a message pointing to the
   Read/Glob/Grep tools; they adapt immediately.
9. **Keep commit titles short**: `<run id> <tier>: <title>`, with the agent's summary in the body.

### Optional extras (ask me if I want them)

- **Demo mode:** record a released run's events (with timings, its diff and the release commit) and replay it through
  the same dashboard without calling Claude; approving a replay really releases the recorded code.
- **Checkpoints:** git tags plus a snapshot of the runs, and a `reset-to <checkpoint>` command that restores the code,
  a fresh database and the backlog.

### Build order (stop after each step for my review)

1. **Confirm the product map:** tiers, folders, test and run commands. Run all the product's tests once. They must
   pass before the factory touches anything.
2. **Factory core:** config, agents, guard, tools, pipeline and command line. Prove the guard with tests. Run one cheap
   agent first, then one small real requirement end to end, from the command line, up to the approval gate.
3. **Factory server:** the endpoints, the event stream, approve and reject, background runs.
4. **Dashboard:** everything listed above.
5. **README:** how to start the product and the factory, run a requirement, approve it, and reset. Then a full dry run.

### Definition of done

- A one-line requirement goes from the dashboard to the approval gate with all tests green, and after I approve, the
  feature is live in my running product.
- The guard demonstrably blocks edits outside an agent's tier, network commands, and pushes.
- The product's tests, plus the factory's own tests, pass.
