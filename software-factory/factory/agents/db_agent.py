"""Stage 4a: the database tier. Alembic migration, SQLAlchemy models and seed data."""
from factory.agents.base import BUILD_TOOLS, STR, AgentSpec, arr, as_json, obj
from factory.agents.build_context import design_context, fix_request
from factory.tools import python_rel

ROLE = """
# Role: Database Engineer
You build the database tier of a feature in the Corner Shop store:
- A new Alembic migration in db/migrations/versions/, hand-written in the style of 0001_initial_schema.py.
  Number it after the current newest revision (e.g. 0002_<short_name>.py with revision "0002" and
  down_revision pointing at the previous revision).
- SQLAlchemy models in api/models/ (one file per model, registered in api/models/__init__.py).
- Seed data in db/seed.py only if the feature needs it.
You may edit only db/ and api/models/. The API and UI agents build on your models next.
Check your work: run the migration against a scratch database with `{py} -m db.reset_db`
(it only touches this workspace's db/store.db) and run the API tests with `{py} -m pytest -q`.
"""

SCHEMA = obj(
    db_changes=obj(summary=STR, migration_file=STR, tables=arr(STR), files=arr(STR)),
)


def task(state, extra):
    return design_context(state) + f"""

Database plan:
{as_json(state['plan']['db'])}

Build the database tier now.""" + fix_request(extra)


SPEC = AgentSpec(
    name="db_agent",
    title="DB Agent",
    role=ROLE.replace("{py}", python_rel()),
    output_schema=SCHEMA,
    task=task,
    tools=BUILD_TOOLS,
    writable=["db/", "api/models/"],
    bash=[r"{py} -m db\.reset_db", r"{py} -m pytest[\w\s./:=-]*", r"{py} -m alembic -c db/alembic\.ini [\w\s.:-]+"],
)
