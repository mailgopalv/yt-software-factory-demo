"""Stage 6: reviews the full diff for quality, security and consistency with the API contract."""
from factory.agents.base import BOOL, STR, AgentSpec, arr, as_json, enum, obj

ROLE = """
# Role: Code Reviewer
You review the complete change for a feature before a human approves it. Use `git diff main...HEAD`
(and Read for context) to see every change. Check:
- Security: SQL injection (raw SQL or string-built queries), missing input validation, data from one
  shopper's session leaking to another, unsafe error messages.
- Contract consistency: the API, the UI's calls in api.js and the tests all match the API contract.
- Quality: follows the existing patterns, no dead code, sensible names, tests cover the acceptance criteria.
Be fair and concrete. Severity "blocker" is only for real bugs or security holes. Your verdict is
"approve" or "request_changes"; the human at the approval gate sees your review either way.
"""

SCHEMA = obj(
    review=obj(
        summary=STR,
        security_ok=BOOL,
        contract_consistent=BOOL,
        findings=arr(obj(severity=enum("blocker", "major", "minor", "info"), file=STR, finding=STR)),
    ),
    verdict=enum("approve", "request_changes"),
)


def task(state, extra):
    return f"""Requirement {state.id}: {state['title']}

Acceptance criteria:
{as_json(state['acceptance_criteria'])}

API contract:
{as_json(state['api_contract'])}

Files changed:
{as_json(extra['files'])}

Test results: {extra['test_summary']}

Review the diff (git diff main...HEAD) and return your review and verdict."""


SPEC = AgentSpec(
    name="reviewer_agent",
    title="Reviewer Agent",
    role=ROLE,
    output_schema=SCHEMA,
    task=task,
    tools=["Read", "Glob", "Grep", "Bash"],
    bash=[r"git (?:--no-pager )?diff[\w\s./:~^-]*", r"git (?:--no-pager )?log[\w\s./:~^=-]*", r"git (?:--no-pager )?show[\w\s./:~^-]*", r"git status[\w\s-]*"],
)
