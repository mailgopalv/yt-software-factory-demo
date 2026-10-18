"""Stage 7: writes the release notes and CHANGELOG entry.

The mechanical release steps (backup, merge, migrate, build, restart, tag) are done by the
pipeline's release tools in factory/tools.py, so they happen the same safe way every time.
"""
from factory.agents.base import STR, AgentSpec, arr, as_json, obj

ROLE = """
# Role: Release Manager
A feature has been approved. Write the release notes and add an entry at the top of CHANGELOG.md
(newest first, under the "# Changelog" intro), in the same format as the existing 1.0.0 entry:
"## [<version>] - <date>" followed by "### Added" / "### Changed" sections with short bullet points
that a store owner would understand. You may edit only CHANGELOG.md.
"""

SCHEMA = obj(
    release_notes=STR,     # 2 to 4 sentences for the release history on the dashboard
    highlights=arr(STR),   # 2 to 4 short bullet points
)


def task(state, extra):
    return f"""Release {extra['version']} on {extra['date']} for requirement {state.id}: {state['title']}

User stories:
{as_json(state['user_stories'])}

Changes:
- Database: {state['db_changes']['summary']}
- API: {state['api_changes']['summary']}
- UI: {state['ui_changes']['summary']}

API endpoints: {as_json([f"{e['method']} {e['path']}" for e in state['api_contract']])}

Update CHANGELOG.md and return the release notes."""


SPEC = AgentSpec(
    name="release_agent",
    title="Release Agent",
    role=ROLE,
    output_schema=SCHEMA,
    task=task,
    tools=["Read", "Edit"],
    writable=["CHANGELOG.md"],
)
