"""Stage 4b: the API tier. FastAPI endpoints, schemas and pytest tests."""
from factory.agents.base import BUILD_TOOLS, STR, AgentSpec, arr, as_json, obj
from factory.agents.build_context import design_context, fix_request
from factory.tools import python_rel

ROLE = """
# Role: Backend Engineer
You build the REST API for a feature in the Corner Shop store, on top of the models the DB agent made:
- Pydantic schemas in api/schemas/, one file per resource.
- A router in api/routes/ (one file per resource), registered in api/main.py.
- pytest tests in api/tests/test_<resource>.py using the existing `client` fixture from conftest.py.
  Cover the happy path, validation errors and not-found cases from the API contract.
Implement the API contract exactly: same paths, fields and status codes. Validate all input with
Pydantic and use the SQLAlchemy ORM for every query (no raw SQL strings).
You may edit only files in api/, except QA's acceptance tests (api/tests/test_acceptance_*), which are the
specification. Run the tests with `{py} -m pytest -q` until they pass.
"""

SCHEMA = obj(
    api_changes=obj(summary=STR, endpoints=arr(STR), files=arr(STR), tests_added=arr(STR)),
)


def task(state, extra):
    return design_context(state) + f"""

Database changes already made by the DB agent:
{as_json(state['db_changes'])}

API plan:
{as_json(state['plan']['api'])}

Build the API tier now.""" + fix_request(extra)


SPEC = AgentSpec(
    name="backend_agent",
    title="Backend Agent",
    role=ROLE.replace("{py}", python_rel()),
    output_schema=SCHEMA,
    task=task,
    tools=BUILD_TOOLS,
    writable=["api/"],
    protected=["api/tests/test_acceptance_"],
    bash=[r"{py} -m pytest[\w\s./:=-]*"],
)
