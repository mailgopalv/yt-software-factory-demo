"""Stage 3: designs the API contract first, then the database change and a build plan per tier."""
from factory.agents.base import STR, AgentSpec, arr, as_json, obj

ROLE = """
# Role: Software Architect
You design the change before anyone builds it. Contract first:
1. The API contract: every new or changed endpoint with method, path, request body, response body and
   status codes. Follow the existing REST style (paths under /api/, JSON, the X-Session-Id header
   identifies the shopper, errors as {"detail": "..."}, prices in whole cents).
2. The database schema change: new tables or columns, with types, keys and constraints. Use an Alembic
   migration that follows db/migrations/versions/0001_initial_schema.py.
3. A short, ordered build plan for each tier (db, api, ui), naming the files to create or modify.
The DB, API and UI agents will build exactly what you specify, in that order, so be precise.
"""

ENDPOINT = obj(method=STR, path=STR, description=STR, request=STR, response=STR, status_codes=arr(STR))
COLUMN = obj(name=STR, type=STR, constraints=STR)

SCHEMA = obj(
    api_contract=arr(ENDPOINT),
    schema_change=obj(summary=STR, tables=arr(obj(name=STR, action=STR, columns=arr(COLUMN))), migration=STR),
    plan=obj(db=arr(STR), api=arr(STR), ui=arr(STR)),
)


def task(state, extra):
    return f"""Requirement {state.id}: {state['title']}

User stories:
{as_json(state['user_stories'])}

Acceptance criteria:
{as_json(state['acceptance_criteria'])}

Impact analysis from the codebase analyst:
{as_json(state['impact_analysis'])}

Affected files:
{as_json(state['affected_files'])}

Design the API contract, the schema change and the build plan."""


SPEC = AgentSpec(name="architect_agent", title="Architect Agent", role=ROLE, output_schema=SCHEMA, task=task)
