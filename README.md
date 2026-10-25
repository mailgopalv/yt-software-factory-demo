# AI Software Factory demo

A small online store that **already exists**, plus an **AI software factory** that adds features to it.
You type a requirement into a dashboard, and a team of Claude agents takes it through the whole SDLC on the
store's real code: requirements, analysis, design, build (database → API → UI), test, review, **your
approval**, and release. Refresh the store and the feature is live.

From the YouTube video by **Explore AI with Gopal**.

```
 Requirement ─▶ 1 Requirements ─▶ 2 Analysis ─▶ 3 Design ─▶ 4 Build ─▶ 5 Test ─▶ 6 Review ─▶ ⏸ You approve ─▶ 7 Release
                                                         DB → API → UI   QA loop:
                                                                         failures go back
                                                                         to the right agent
```

| Folder | What it is |
|---|---|
| `store/` | **Corner Shop**: React + Vite frontend, FastAPI API, SQLite database, ~30 tests (pytest, Vitest, Playwright). Its own git repo, unpacked from `store.bundle` by setup |
| `software-factory/` | The factory: 9 agents built with the Claude Agent SDK, the pipeline, a FastAPI server and the live dashboard. See [software-factory/README.md](software-factory/README.md) |

## What you need

- **Python 3.11+**, **Node.js 20+** and **git**
- For **demo mode**: nothing else. It replays recorded runs and uses no Claude usage.
- For **real agent runs**: [Claude Code](https://claude.com/claude-code) installed and logged in with your Claude
  subscription (`claude`, then `/login`), **or** an Anthropic API key (see [Real runs](#real-runs)).

## Set up (once)

**Windows** (PowerShell):
```powershell
git clone https://github.com/mailgopalv/yt-software-factory-demo.git software-factory-demo
cd software-factory-demo
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

**Mac** (Terminal):
```bash
git clone https://github.com/mailgopalv/yt-software-factory-demo.git software-factory-demo
cd software-factory-demo
chmod +x setup.sh && ./setup.sh
```

Setup unpacks the store, installs its packages and Playwright's browser, builds its database, and installs the
factory. It takes a few minutes the first time and is safe to run again.

> **Windows tip:** if PowerShell refuses to run scripts, either keep using `powershell -ExecutionPolicy Bypass -File <script>`
> or allow local scripts once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Try it in demo mode (no Claude usage)

Open **two terminals**.

| | Windows | Mac |
|---|---|---|
| 1. Start the store | `cd store` then `.\run-store.ps1` | `cd store && ./run-store.sh` |
| 2. Start the factory in demo mode | `cd software-factory` then `.\run-factory.ps1 -Demo` | `cd software-factory && ./run-factory.sh --demo` |

Then:

1. Open the store at **http://localhost:5173** and the dashboard at **http://localhost:8000**, side by side.
2. In the dashboard's **New requirement** box, type a wishlist requirement, for example
   *"Shoppers can save products to a wishlist with a heart button and a Wishlist page"*, and click **Send to factory**.
3. Watch the agents work. The run is a recording of a real run, played back at 3× speed.
4. At the gate, click **✔ Approve & release**. The factory really merges the recorded code into the store,
   migrates the database and restarts the API.
5. Refresh the store: heart buttons, a Wishlist page, and **v1.1.0** in the footer.
6. Now type a discount requirement, e.g. *"Shoppers can apply a discount code at checkout"*, approve it, and
   try the code `SAVE10` at checkout (the store becomes **v1.2.0**).

Demo mode picks the recording whose keywords match what you type (`wishlist`, `heart`… or `discount`,
`coupon`…). Anything else gets a polite "no recording matches" message.

## Start again from any point

The store has four checkpoints. Resetting restores the store's code, a fresh database and the dashboard's
backlog; earlier runs are archived to `software-factory/runs-archive/`, never deleted.

| Checkpoint | State |
|---|---|
| `checkpoint-1-store-only` | The store on its own (v1.0) |
| `checkpoint-2-factory-added` | Same store, ready for the factory (start here for the wishlist demo) |
| `checkpoint-3-wishlist` | After the wishlist release (v1.1.0; start here for the discount demo) |
| `checkpoint-4-discounts` | After the discount codes release (v1.2.0) |

```powershell
cd software-factory
.\reset-to.ps1 checkpoint-2-factory-added      # Mac: ./reset-to.sh checkpoint-2-factory-added
```

Run it with no name to list the checkpoints. Refresh both browser tabs afterwards.

## Real runs

Start the factory **without** `-Demo` / `--demo` and type any requirement for the store, for example
*"Shoppers can search products by name"*. The agents really read, write and test the code on a feature branch.
A run takes roughly 10 to 20 minutes and stops at the approval gate for you.

- **Login:** by default the agents use your Claude Code login (`auth: subscription` in
  `software-factory/factory.yaml`). Runs count against your plan's usage limits. A full run is a meaningful slice
  of a Pro plan's 5-hour window; `model: claude-sonnet-5-5` in `factory.yaml` stretches it further. Check that your
  plan's terms cover how you use it.
- **API key instead:** set `auth: api_key` in `factory.yaml`, copy `software-factory/.env.example` to `.env`, and
  paste your key. You pay per use.
- **If a usage limit hits mid-run**, the run stops cleanly. Continue after the limit resets with the **↻ Resume**
  button on the dashboard (or `python -m factory resume REQ-00x`).
- **Turn your own runs into recordings** for demo mode: `python -m factory record REQ-00x --name search --keywords search,find`.

Safety: every agent is limited to the store's folder, to the files of its own tier, and to an allow-list of shell
commands, with no network access. Every tool call is checked by a guard before it runs. Nothing is merged without
your approval.

## Build one for your own product

This factory is tailored to Corner Shop. To create one for **your** three-tier app, open your product's repo in
Claude Code and give it [SOFTWARE-FACTORY-PROMPT.md](SOFTWARE-FACTORY-PROMPT.md). It describes the agents, the
safety guard, the approval gate and the dashboard, asks about your stack first, builds it step by step, and
includes the pitfalls we hit building this one. Tweak it to suit your product.

## Troubleshooting

| Problem | Fix |
|---|---|
| "port already in use" / a page won't load | Something else is on 8000, 8001 or 5173 (often an earlier copy of the store or factory). Close it, or restart your computer's terminal windows |
| No "▶ demo replay" badge on the dashboard, or a real run starts instead | The factory was started without `-Demo` / `--demo`. Stop it (Ctrl+C) and start it again with the flag |
| "Not logged in to Claude Code" | Run `claude`, type `/login`, then try again (or use demo mode) |
| "The store has uncommitted changes" | Something edited files in `store/`. Use `reset-to` to return to a checkpoint |
| "The store isn't at the checkpoint this recording starts from" | Reset first: `checkpoint-2-factory-added` for the wishlist demo, `checkpoint-3-wishlist` for the discount demo |
| The store doesn't show a release | Refresh the browser. The API restarts by itself within a couple of seconds |

## Run the tests

```powershell
cd store;            .\test-store.ps1                       # Mac: ./test-store.sh  (store: pytest, Vitest, Playwright)
cd software-factory; .\.venv\Scripts\python -m pytest       # Mac: .venv/bin/python -m pytest  (the factory itself)
```

## For the maintainer: refreshing store.bundle

After changing the store's history (new checkpoints or recordings):
```bash
git -C store bundle create ../store.bundle HEAD main checkpoint-1-store-only checkpoint-2-factory-added checkpoint-3-wishlist checkpoint-4-discounts
```
