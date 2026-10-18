"""The factory's agents, one file each."""
from factory.agents import (
    architect_agent,
    backend_agent,
    codebase_analyst,
    db_agent,
    frontend_agent,
    qa_agent,
    release_agent,
    requirements_agent,
    reviewer_agent,
)

AGENTS = {
    m.SPEC.name: m.SPEC
    for m in (
        requirements_agent, codebase_analyst, architect_agent,
        db_agent, backend_agent, frontend_agent,
        qa_agent, reviewer_agent, release_agent,
    )
}

# Which build agent owns each tier, for QA's fix loop.
# "qa" means one of QA's own acceptance tests was wrong; QA fixes it.
TIER_AGENTS = {"db": "db_agent", "api": "backend_agent", "ui": "frontend_agent", "qa": "qa_agent"}
