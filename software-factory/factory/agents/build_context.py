"""The design context every build agent (DB, API, UI) receives, plus QA feedback on fix loops."""
from factory.agents.base import as_json


def design_context(state) -> str:
    return f"""Requirement {state.id}: {state['title']}

Acceptance criteria:
{as_json(state['acceptance_criteria'])}

API contract (build exactly this):
{as_json(state['api_contract'])}

Schema change:
{as_json(state['schema_change'])}

Build plan:
{as_json(state['plan'])}"""


def fix_request(extra: dict) -> str:
    """When QA sends work back, the agent gets the failure details instead of a fresh build request."""
    if not extra.get("qa_feedback"):
        return ""
    return f"""

## QA sent this back to you (loop {extra['iteration']})
Your earlier work is already in the files. Fix the problem below; do not start over.

{extra['qa_feedback']}

Failing test output:
{extra.get('failure_output', '')}"""
