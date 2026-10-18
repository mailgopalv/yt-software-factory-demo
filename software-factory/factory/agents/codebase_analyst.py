"""Stage 2: reads the store and works out what the change touches in each tier."""
from factory.agents.base import STR, AgentSpec, arr, as_json, enum, obj

ROLE = """
# Role: Codebase Analyst
You read the existing Corner Shop codebase and work out exactly where a new feature fits.
Map the change to each tier: database (db/, api/models/), API (api/routes, api/schemas, api/tests)
and UI (frontend/src). Name real files and the existing patterns the build agents should copy.
Point out risks: things that could break, and existing tests that may need updating.
Do not write code and do not design the API; the architect does that next.
"""

SCHEMA = obj(
    impact_analysis=obj(
        summary=STR,
        db=STR,
        api=STR,
        ui=STR,
        patterns_to_follow=arr(STR),
        risks=arr(STR),
    ),
    affected_files=arr(obj(path=STR, change=enum("new", "modify"), tier=enum("db", "api", "ui", "e2e"), reason=STR)),
)


def task(state, extra):
    return f"""Requirement {state.id}: {state['title']}

User stories:
{as_json(state['user_stories'])}

Acceptance criteria:
{as_json(state['acceptance_criteria'])}

Read the store codebase and return the impact analysis and the list of files to create or modify."""


SPEC = AgentSpec(name="codebase_analyst", title="Codebase Analyst", role=ROLE, output_schema=SCHEMA, task=task)
