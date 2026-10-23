# Verified Brain environment

Checked 9 October 2026 in Elyes's Desktop checkout. Every one of the 55 applicable entries in requirements-lock.txt matches the installed version. No dependencies were added or upgraded for direct Gemini or the browser console.

| Item | Local value | Basis |
| --- | --- | --- |
| Python | 3.12.13 | CIVIS setup selects 3.12; this is the installed patch version |
| FastAPI | 0.142.2 | Brain lock; matches inspected Twin requirements |
| Uvicorn | 0.54.0 | Brain lock; matches Twin |
| Pydantic | 2.13.5 | Brain lock; matches Twin |
| pydantic-settings | 2.15.0 | Brain lock; matches Twin |
| MCP SDK | 2.3.0 | Brain lock; matches Twin |
| MCP protocol | 2026-07-28 | Final agreed decision report; separate from SDK package version |
| httpx / httpx2 | 0.28.1 / 2.13.1 | Existing HTTP and MCP transport dependencies |
| jsonschema | 4.26.0 | Existing lock; local Plan and discovery validation |
| google-genai | 2.28.0 | Direct Gemini Interactions API |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 | Existing test pins |
| Ruff | 0.16.10 | Existing lint pin |
| Gemini model | gemini-3.5-flash-lite | Selected free-tier model; explicit local configuration |

The final decision report and session summary specify Python, FastAPI/Pydantic and the MCP protocol. They do not prescribe exact Python patch or library versions. Package pins are repository compatibility choices, not additional triplet agreements. Twin requirements were inspected on origin/twin-full-history; this does not merge or approve that branch. Guardian's inspected repository branch has no Python dependency manifest, so its installed packages cannot be verified from it.

From brain/, check all applicable locked packages without printing keys or making requests:

~~~powershell
.\.venv\Scripts\python.exe scripts/doctor.py
~~~

Only Elyes changes dependency pins. A version match does not settle unconfirmed Guardian schemas, preview, pending confirmation or shared-domain cap discovery. Track those in PARTNER_GAPS.md.

The [Gemini Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview) is supported by the existing Google GenAI SDK. [Structured output](https://ai.google.dev/gemini-api/docs/structured-output) constrains the Plan; Brain validates it locally before any mock approval or execution. Requests are stateless (store=false), use a 2,048-token output limit and low thinking, and include no search tools. Only final output is displayed. Pro was not selected because the user chose to preserve the free-tier requirement; see [Google pricing](https://ai.google.dev/gemini-api/docs/pricing).
