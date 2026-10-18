"""Loads factory.yaml, and sets up how the agents log in to Claude."""
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

FACTORY_DIR = Path(__file__).resolve().parent.parent
# Where runs are saved. FACTORY_RUNS_DIR points it elsewhere (demo recordings, tests).
RUNS_DIR = Path(os.getenv("FACTORY_RUNS_DIR") or FACTORY_DIR / "runs")

AUTH_MODES = ("subscription", "api_key")
# Either of these would silently take priority over the Claude subscription login.
KEY_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


@dataclass
class AgentLimits:
    max_turns: int
    max_budget_usd: float


@dataclass
class Config:
    store_path: Path
    main_branch: str
    web_url: str
    api_url: str
    auth: str
    model: str
    effort: str
    qa_max_loops: int
    default_limits: AgentLimits
    agent_limits: dict[str, AgentLimits] = field(default_factory=dict)
    api_key: str = ""
    demo_enabled: bool = False
    demo_speed: float = 3.0
    demo_max_gap: float = 4.0
    demo_show_badge: bool = True

    def limits_for(self, agent_name: str) -> AgentLimits:
        return self.agent_limits.get(agent_name, self.default_limits)


def load_config(path: Path = FACTORY_DIR / "factory.yaml") -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    auth = raw.get("auth", "subscription")
    if auth not in AUTH_MODES:
        raise ValueError(f"auth in factory.yaml must be one of {AUTH_MODES}, not {auth!r}")
    api_key = ""
    if auth == "api_key":
        load_dotenv(FACTORY_DIR / ".env")
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
    else:
        # The agents inherit this process's environment. Remove any key so they use the
        # Claude Code login (your subscription) instead of billing an API account.
        for name in KEY_VARIABLES:
            os.environ.pop(name, None)

    limits = raw.get("limits", {})
    default_limits = AgentLimits(limits.get("max_turns", 40), limits.get("max_budget_usd", 3.0))
    agent_limits = {
        name: AgentLimits(
            values.get("max_turns", default_limits.max_turns),
            values.get("max_budget_usd", default_limits.max_budget_usd),
        )
        for name, values in (raw.get("agents") or {}).items()
    }

    demo = raw.get("demo") or {}
    demo_env = os.getenv("DEMO_MODE", "").strip().lower()
    demo_enabled = demo_env in ("1", "true", "yes", "on") if demo_env else bool(demo.get("enabled", False))

    store = raw["store"]
    return Config(
        store_path=(path.parent / store["path"]).resolve(),
        main_branch=store.get("main_branch", "main"),
        web_url=store.get("web_url", "http://localhost:5173"),
        api_url=store.get("api_url", "http://localhost:8001"),
        auth=auth,
        model=raw.get("model", "claude-opus-5-5"),
        effort=raw.get("effort", "medium"),
        qa_max_loops=raw.get("qa", {}).get("max_loops", 3),
        default_limits=default_limits,
        agent_limits=agent_limits,
        api_key=api_key,
        demo_enabled=demo_enabled,
        demo_speed=float(demo.get("speed", 3)),
        demo_max_gap=float(demo.get("max_gap_seconds", 4)),
        demo_show_badge=bool(demo.get("show_badge", True)),
    )
