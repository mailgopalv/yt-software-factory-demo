"""Stage 1: turns a one-line requirement into user stories and acceptance criteria."""
from factory.agents.base import STR, AgentSpec, arr, obj

ROLE = """
# Role: Requirements Analyst
You turn a business requirement for the Corner Shop online store into clear user stories and
testable acceptance criteria. Look at the store briefly (pages in frontend/src/pages, API in api/routes)
so the stories fit what already exists, but do not design the solution: later agents do that.
- Write 2 to 4 user stories in the form "As a <role>, I want <goal>, so that <benefit>".
- Write 4 to 8 acceptance criteria in Given / When / Then form. Each must be testable.
- Keep the scope to what was asked. List anything sensible but not asked for under out_of_scope.
- Shoppers are identified by their browser session (there are no logins).
"""

SCHEMA = obj(
    title=STR,              # 1-3 words, e.g. "Wishlist"
    user_stories=arr(STR),
    acceptance_criteria=arr(STR),
    out_of_scope=arr(STR),
)


def task(state, extra):
    return f"""Requirement {state.id}:

{state['requirement']}

Return a short title (1 to 3 words), user stories, acceptance criteria and out-of-scope items."""


SPEC = AgentSpec(name="requirements_agent", title="Requirements Agent", role=ROLE, output_schema=SCHEMA, task=task)
