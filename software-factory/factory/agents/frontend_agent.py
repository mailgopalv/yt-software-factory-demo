"""Stage 4c: the UI tier. React components and pages, API calls, Vitest tests and one Playwright journey."""
from factory.agents.base import BUILD_TOOLS, STR, AgentSpec, arr, as_json, obj
from factory.agents.build_context import design_context, fix_request

ROLE = """
# Role: Frontend Engineer
You build the user interface for a feature in the Corner Shop store (React 18 + Vite + React Router 6):
- API calls go in frontend/src/api.js only, using the existing request() helper.
- Pages in frontend/src/pages/, reusable pieces in frontend/src/components/, routes in App.jsx,
  links in components/Header.jsx. Shared state follows the CartContext.jsx pattern if it is needed.
- Styles in frontend/src/styles.css, matching the existing look (cards, .button.primary, the brand colour).
- Vitest tests in frontend/src/__tests__/, mocking '../api' and rendering with renderPage() from
  src/test/renderPage.jsx, like the existing tests. Every test file needs vi.mock('../api').
  If you add a provider around the app in main.jsx, add it to renderPage() too.
- One Playwright end-to-end test of the feature's main user journey, in a new file
  e2e/tests/<feature>.spec.js, in the style of e2e/tests/shop.spec.js (each test gets a fresh browser,
  so a fresh shopper session). It runs against the real API and database.
- Use accessible names (aria-label on icon buttons, data-testid where the existing code uses them).
Use the API exactly as the contract says. You may edit only files in frontend/src/ and e2e/tests/.
Run the unit tests with `npm --prefix frontend test` and the end-to-end tests with `npm --prefix e2e test`
until they pass.
"""

SCHEMA = obj(
    ui_changes=obj(summary=STR, components=arr(STR), files=arr(STR), tests_added=arr(STR)),
)


def task(state, extra):
    return design_context(state) + f"""

API built by the backend agent:
{as_json(state['api_changes'])}

UI plan:
{as_json(state['plan']['ui'])}

Build the UI tier now, including the Playwright journey.""" + fix_request(extra)


SPEC = AgentSpec(
    name="frontend_agent",
    title="Frontend Agent",
    role=ROLE,
    output_schema=SCHEMA,
    task=task,
    tools=BUILD_TOOLS,
    writable=["frontend/src/", "e2e/tests/"],
    bash=[
        r"npm --prefix (?:frontend|e2e) (?:run )?test[\w\s./:=-]*",
        r"npm (?:run )?test[\w\s./:=-]*",
        r"npx vitest run[\w\s./:=-]*",
        r"npx playwright test[\w\s./:=-]*",
    ],
)
