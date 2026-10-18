"""Stage 5: QA. Two jobs, like a real QA engineer:

1. AUTHOR_SPEC writes independent acceptance tests from the acceptance criteria and the API contract,
   before running anything. The developer agents may not edit these tests.
2. SPEC (triage) runs only when a suite fails: it works out which tier is at fault and what to fix,
   and the pipeline sends the work back to that tier's agent.

The pipeline itself runs the suites, so the pass/fail counts are exact.
"""
from factory.agents.base import BUILD_TOOLS, STR, AgentSpec, arr, as_json, enum, obj
from factory.agents.build_context import fix_request
from factory.tools import python_rel, slugify

ACCEPTANCE_PREFIX = "api/tests/test_acceptance_"

AUTHOR_ROLE = """
# Role: QA Engineer (acceptance tests)
Before the full test run, you write independent acceptance tests for the new feature, straight from the
acceptance criteria and the API contract. You test what the business asked for, including the edge cases
the criteria imply: invalid input, unknown ids, limits, duplicates, shoppers' sessions kept separate,
money rounding.
- Write one pytest file, {file}, using the existing `client` fixture from api/tests/conftest.py.
  The X-Session-Id header identifies the shopper; the seed products are in db/seed.py.
- One short, readable test per acceptance criterion that can be checked through the API, named after it.
  A QA lead should understand each test at a glance.
- Work from the criteria and the contract, not from the developers' tests. Read the API code only to
  confirm exact paths and field names.
- Run your file with `{py} -m pytest {file} -q`. Failing tests are findings: do not weaken a test to make it
  pass. Fix a test only if the test itself is wrong (for example a field name that differs from the contract).
You may edit only {file}.
"""

AUTHOR_SCHEMA = obj(
    acceptance_tests=obj(summary=STR, file=STR, tests=arr(STR), findings=arr(STR)),
)

TRIAGE_ROLE = """
# Role: QA Engineer (triage)
Tests have failed on a new feature in the Corner Shop store. Read the failing test output and the
code it points at, and decide who must fix it:
- "db" for migrations, models or seed data (db/, api/models/)
- "api" for endpoints, schemas or the developers' API tests (api/)
- "ui" for React components, pages, api.js, Vitest tests or the Playwright test (frontend/src/, e2e/tests/)
- "qa" only if one of QA's own acceptance tests (api/tests/test_acceptance_*) is wrong because it
  contradicts the API contract. QA's acceptance tests are the specification: when the code disagrees
  with them, the code is wrong.
An end-to-end (Playwright) failure belongs to whichever tier actually broke. Give precise fix instructions:
the file, what is wrong, and what the correct behaviour is. You only diagnose; you do not edit code.
"""

SCHEMA = obj(
    tier=enum("db", "api", "ui", "qa"),
    diagnosis=STR,
    fix_instructions=STR,
)


def acceptance_file(state) -> str:
    return f"{ACCEPTANCE_PREFIX}{slugify(state['title'], 24).replace('-', '_')}.py"


def author_task(state, extra):
    file = state.get("acceptance_tests", {}).get("file") or acceptance_file(state)
    return f"""Requirement {state.id}: {state['title']}

Acceptance criteria:
{as_json(state['acceptance_criteria'])}

API contract:
{as_json(state['api_contract'])}

Write the acceptance tests in {file} and run them.""" + fix_request(extra)


def triage_task(state, extra):
    return f"""Requirement {state.id}: {state['title']} (QA loop {extra['iteration']})

API contract:
{as_json(state['api_contract'])}

Failing suites:
{extra['failure_output']}

Diagnose the failure and say who must fix it."""


class AuthorSpec(AgentSpec):
    """The author's file name depends on the feature, so its role and permissions are filled in per run."""

    def for_run(self, state) -> AgentSpec:
        file = state.get("acceptance_tests", {}).get("file") or acceptance_file(state)
        return AgentSpec(
            name=self.name, title=self.title, output_schema=self.output_schema, task=self.task, tools=self.tools,
            role=AUTHOR_ROLE.replace("{file}", file).replace("{py}", python_rel()),
            writable=[file],
            bash=[r"{py} -m pytest[\w\s./:=-]*"],
        )


AUTHOR_SPEC = AuthorSpec(name="qa_agent", title="QA Agent", role=AUTHOR_ROLE, output_schema=AUTHOR_SCHEMA,
                         task=author_task, tools=BUILD_TOOLS)

SPEC = AgentSpec(name="qa_agent", title="QA Agent", role=TRIAGE_ROLE, output_schema=SCHEMA, task=triage_task)
