"""Command-line interface for the factory.

  python -m factory run "Shoppers can save products to a wishlist"   # runs to the approval gate
  python -m factory approve REQ-001 --by Gopal                       # releases it
  python -m factory reject REQ-001 --by Gopal --reason "..."         # discards it
  python -m factory resume REQ-001                                   # continues a failed run
  python -m factory status [REQ-001]                                 # shows runs
"""
import argparse
import asyncio
import sys
import textwrap
from datetime import datetime

from factory import demo
from factory.agents import AGENTS
from factory.config import Config, load_config
from factory.pipeline import Pipeline, PipelineError, test_summary
from factory.state import RunState, list_runs

BOLD, DIM, RESET = "\x1b[1m", "\x1b[2m", "\x1b[0m"
GREEN, RED, YELLOW, CYAN, MAGENTA = "\x1b[32m", "\x1b[31m", "\x1b[33m", "\x1b[36m", "\x1b[35m"
COST_LABEL = "$"  # set to "API-equivalent $" in subscription mode, where nothing is billed
STAGE_NUMBER = {"requirements": "1", "analysis": "2", "design": "3", "build": "4", "qa": "5", "review": "6", "approval": "⏸", "release": "7"}


def title(agent: str | None) -> str:
    return AGENTS[agent].title if agent in AGENTS else (agent or "")


def short(text: str, width: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def print_event(e: dict) -> None:
    """Prints the interesting events of a run as they happen."""
    t, agent = e["type"], e.get("agent")
    who = f"{MAGENTA}{title(agent)}{RESET}"
    if t == "stage" and e["status"] == "active":
        print(f"\n{BOLD}{CYAN}━━ Stage {STAGE_NUMBER[e['stage']]} · {e['title']} ━━{RESET}")
    elif t == "stage" and e["status"] == "failed":
        print(f"{RED}✗ Stage {e['title']} failed{RESET}")
    elif t == "agent_started":
        print(f"{BOLD}▶ {who}{BOLD} is working{RESET}")
    elif t == "agent_message":
        print(textwrap.indent(short(e["text"], 300), "   💬 "))
    elif t == "tool_call":
        print(f"   {DIM}🔧 {e['tool']:<5} {short(e['summary'], 120)}{RESET}")
    elif t == "tool_result" and e["is_error"]:
        print(f"   {YELLOW}↳ {short(e['preview'], 140)}{RESET}")
    elif t == "tool_denied":
        print(f"   {RED}⛔ guard blocked {e['tool']}: {short(e['reason'], 140)}{RESET}")
    elif t == "agent_finished":
        print(f"   {GREEN}✓ {title(agent)} done{RESET} {DIM}({e['seconds']}s, {e['turns']} turns, {COST_LABEL}{e['cost_usd']:.2f}){RESET}")
    elif t == "state_updated" and agent:
        print(f"   {DIM}📝 run state ← {', '.join(e['keys'])}{RESET}")
    elif t == "branch_created":
        print(f"   🌿 branch {BOLD}{e['branch']}{RESET}")
    elif t == "tier_started":
        print(f"\n   {BOLD}[{e['tier'].upper()} lane]{RESET}")
    elif t == "tier_finished" and e.get("commit"):
        print(f"   {DIM}commit {e['commit']}{RESET}")
    elif t == "tests_started":
        print(f"   🧪 {e['name']} ({e['label']})…", end="", flush=True)
    elif t == "tests_finished":
        colour, mark = (GREEN, "✓") if e["ok"] else (RED, "✗")
        print(f" {colour}{mark} {e['passed']} passed, {e['failed']} failed{RESET} {DIM}({e['seconds']}s){RESET}")
    elif t == "qa_sendback":
        print(f"\n   {YELLOW}{BOLD}🔁 QA loop {e['loop']}: sending back to {title(e['to_agent'])}{RESET}")
        print(textwrap.indent(short(e["diagnosis"], 300), "      "))
    elif t == "qa_passed":
        print(f"   {GREEN}{BOLD}All suites green{RESET}" + (f" after {e['loops']} QA loop(s)" if e["loops"] else ""))
    elif t == "release_step":
        print(f"   🚀 {e['step']}: {e['detail']}")
    elif t == "approved":
        print(f"\n{GREEN}{BOLD}✔ Approved by {e['by']}{RESET}")
    elif t == "released":
        print(f"\n{GREEN}{BOLD}🎉 Released v{e['version']}: {e['title']}. Refresh the store!{RESET}")
    elif t == "rejected":
        print(f"\n{YELLOW}{BOLD}Rejected by {e['by']}.{RESET} Branch {e.get('branch_kept')} kept for reference.")
    elif t == "usage_limit" and e["status"] != "allowed":
        used = f"{e['utilization']:.0%} used" if e.get("utilization") is not None else "limit reached"
        resets = f", resets {datetime.fromtimestamp(e['resets_at']):%H:%M}" if e.get("resets_at") else ""
        print(f"   {YELLOW}⚠ Claude usage ({e.get('window') or 'plan'}): {used}{resets}{RESET}")
    elif t == "run_resumed":
        print(f"{BOLD}↻ Resuming {e['run_id']} from the {e['stage']} stage{RESET}")
    elif t == "run_failed":
        print(f"\n{RED}{BOLD}✗ Run failed: {e['error']}{RESET}")
        if e.get("resumable"):
            print(f"   Continue later with: python -m factory resume {e['run_id']}")


def print_gate(state: RunState) -> None:
    s = state.data
    print(f"\n{BOLD}{YELLOW}⏸  {s['id']} is waiting for your approval{RESET}")
    print(f"   Requirement: {s['title']}  ({s['branch']})")
    print(f"   Tests:       {test_summary(s['test_results'], s['baseline_tests'])}")
    print(f"   QA loops:    {s.get('iteration', 0)}")
    print(f"   Review:      {s['verdict']}: {short(s['review']['summary'], 200)}")
    for f in s["review"]["findings"]:
        print(f"                - [{f['severity']}] {f['file']}: {short(f['finding'], 150)}")
    print(f"   Changed:     {len(s['files_changed'])} files")
    for f in s["files_changed"]:
        print(f"                {GREEN}+{f['added']:<4}{RESET}{RED}-{f['removed']:<4}{RESET} {f['path']}")
    if s.get("migration_sql"):
        print(f"   Migration SQL:\n{textwrap.indent(s['migration_sql'], '      ')}")
    print(f"   Cost so far: {COST_LABEL}{s.get('cost_usd', 0):.2f}")
    print(f"   Full diff:   {state.run_dir / 'diff.patch'}")
    print(f"\n   Approve:  python -m factory approve {s['id']} --by <your name>")
    print(f"   Reject:   python -m factory reject {s['id']} --by <your name> --reason \"...\"")


def print_status(run_id: str | None) -> None:
    if run_id:
        state = RunState.load(run_id)
        s = state.data
        print(f"{BOLD}{s['id']}{RESET} {s.get('title', '')} [{s['status']}]")
        for stage, status in s.get("stages", {}).items():
            print(f"   {stage:<13} {status}")
        if s["status"] == "awaiting_approval":
            print_gate(state)
        if s.get("error"):
            print(f"   {RED}{s['error']}{RESET}")
        return
    runs = list_runs()
    if not runs:
        print("No runs yet.")
    for s in runs:
        extra = f" v{s['version']}" if s.get("version") else ""
        print(f"{s['id']}  {s['status']:<18} {s.get('title') or short(s['requirement'], 60)}{extra}")


def print_header(config: Config) -> None:
    login = "Claude subscription" if config.auth == "subscription" else "API key"
    if config.demo_enabled:
        login = f"DEMO MODE (replaying recordings at {config.demo_speed:g}x)"
    print(f"{BOLD}AI Software Factory{RESET} {DIM}· store: {config.store_path} · model: {config.model} · login: {login}{RESET}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m factory", description="AI Software Factory")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="run a requirement up to the approval gate")
    p.add_argument("requirement")
    p = sub.add_parser("approve", help="approve a run and release it")
    p.add_argument("run_id")
    p.add_argument("--by", default="Gopal")
    p = sub.add_parser("reject", help="reject a run and discard its changes")
    p.add_argument("run_id")
    p.add_argument("--by", default="Gopal")
    p.add_argument("--reason", default="")
    p = sub.add_parser("execute", help="run a requirement already in the backlog (used by the dashboard)")
    p.add_argument("run_id")
    p = sub.add_parser("resume", help="continue a failed run from where it stopped")
    p.add_argument("run_id")
    p = sub.add_parser("status", help="list runs, or show one run")
    p.add_argument("run_id", nargs="?")
    p = sub.add_parser("record", help="turn a released run into a demo recording (demo/<name>.json)")
    p.add_argument("run_id")
    p.add_argument("--name", required=True)
    p.add_argument("--keywords", required=True, help="comma-separated words that pick this recording, e.g. wishlist,heart")
    sub.add_parser("recordings", help="list demo recordings")
    sub.add_parser("checkpoints", help="list the store's checkpoints")
    p = sub.add_parser("save-checkpoint", help="tag the store and snapshot the runs as a checkpoint")
    p.add_argument("name")
    p = sub.add_parser("reset-to", help="restore the store, its database and the runs to a checkpoint")
    p.add_argument("name")
    args = parser.parse_args()

    config = load_config()
    global COST_LABEL
    if config.auth == "subscription":
        COST_LABEL = "API-equivalent $"
    pipeline = Pipeline(config, listeners=[print_event])
    try:
        if args.command == "run":
            print_header(config)
            state = asyncio.run(pipeline.start(args.requirement))
            if state["status"] == "awaiting_approval":
                print_gate(state)
            return 0 if state["status"] == "awaiting_approval" else 1
        if args.command in ("resume", "execute"):
            print_header(config)
            run = pipeline.resume if args.command == "resume" else pipeline.execute
            state = asyncio.run(run(args.run_id))
            if state["status"] == "awaiting_approval":
                print_gate(state)
            return 0 if state["status"] == "awaiting_approval" else 1
        if args.command == "approve":
            state = asyncio.run(pipeline.approve(args.run_id, args.by))
            return 0 if state["status"] == "released" else 1
        if args.command == "reject":
            pipeline.reject(args.run_id, args.by, args.reason)
            return 0
        if args.command == "record":
            path = demo.record(config, args.run_id, args.name, [k.strip() for k in args.keywords.split(",") if k.strip()])
            print(f"{GREEN}Recorded {args.run_id} as {path}{RESET}")
            return 0
        if args.command == "recordings":
            for r in demo.recordings():
                print(f"{BOLD}{r['name']}{RESET}  {r['title']} (from {r['source_run']}, releases v{r['release']['version']})  keywords: {', '.join(r['keywords'])}")
            return 0
        if args.command == "checkpoints":
            for name in demo.list_checkpoints(config):
                print(f"{BOLD}{name}{RESET}  {demo.CHECKPOINTS.get(name, '')}")
            return 0
        if args.command == "save-checkpoint":
            commit = demo.save_checkpoint(config, args.name)
            print(f"{GREEN}Saved {args.name} at {commit} (store tag + runs snapshot){RESET}")
            return 0
        if args.command == "reset-to":
            demo.reset_to(config, args.name, say=lambda line: print(f"   {line}"))
            print(f"{GREEN}{BOLD}Reset to {args.name}.{RESET} Refresh the store and the dashboard.")
            return 0
        print_status(args.run_id)
        return 0
    except (PipelineError, FileNotFoundError, demo.DemoError) as err:
        print(f"{RED}{err}{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
