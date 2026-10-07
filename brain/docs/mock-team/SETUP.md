# Exact software and environment setup

## Install on every member's computer

Everyone uses the same stack, even when their task uses only part of it:

1. **Git** for cloning and pushing. Windows installer: https://git-scm.com/downloads/win
2. **VS Code**, with Microsoft's **Python** and **Pylance** extensions. https://code.visualstudio.com/
3. **uv** for creating the environment and installing the lock file. On Windows: `winget install --id=astral-sh.uv -e`. Restart the terminal afterward.
4. **Python 3.12**, managed by uv. The setup script selects 3.12 and can download it if absent. Do not use a global Python 3.14 environment for this mock.
5. A GitHub account. Sign into VS Code's GitHub support or Git Credential Manager with your own account. Elyes needs each username to grant write access. Never use Elyes's login or token.

No Docker, Node.js, React, database, GPU, model download, LangChain or CrewAI is required for this checkpoint. GitHub Desktop and Postman are optional, not required. The MCP Inspector needs Node.js, so it is optional and not on the critical path.

## Python modules installed by the common setup

| Module | Version | Purpose |
| --- | --- | --- |
| FastAPI | 0.142.2 | HTTP service and health route |
| Uvicorn | 0.54.0 | Runs the service |
| Pydantic | 2.13.5 | Validates shared data and AI outputs |
| pydantic-settings | 2.15.0 | Reads local `.env` settings |
| Official MCP SDK | 2.3.0 | MCP server/client, matching Trinity's current branch |
| httpx / httpx2 | 0.28.1 / 2.13.1 | HTTP tests/AI SDK and MCP v2 transport respectively |
| google-genai | 2.28.0 | Official Gemini API client |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 | Tests and async tests |
| Ruff | 0.16.10 | Common lint checks |

`requirements-lock.txt` pins these and their transitive dependencies across Windows/Linux. Nobody installs a different version independently. Any dependency change goes through Elyes, who regenerates the lock file and tells everyone to rerun setup.

## Per-person additions

| Member | Additional software/account | What to concentrate on |
| --- | --- | --- |
| Elyes | GitHub CLI is useful for reviewing/settings; local Gemini key for integration smoke tests | MCP, FastAPI, Pydantic, async tests, peer configuration |
| Yassine | None beyond common setup; no AI API key needed for detection tests | Pydantic, plain Python, pytest |
| Meriem | Google AI Studio account and her own free-tier Gemini API key | google-genai, Pydantic structured output, async tests |
| Maram | None beyond common setup; no AI API key for recorded fixtures | pytest, pytest-asyncio, JSON fixtures, MCP contract tests |

Runtime AI default: **`gemini-3.5-flash-lite`**. Google's current pricing lists a free tier for its input/output. Free usage has limits; verify model access in the account and keep Cloud Billing disabled. Do not silently fall back to a paid model. Only synthetic city data goes to the free API.

## Clone and select your branch

Run in PowerShell, replacing the branch on the third line with your name from the table:

```powershell
git clone https://github.com/CodeSailor411/triplet-04.git
cd triplet-04
git switch --track origin/codex/civis-yassine
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
.\.venv\Scripts\python.exe -m civis_brain
```

Branches: `codex/civis-elyes`, `codex/civis-yassine`, `codex/civis-meriem`, `codex/civis-maram`.
On the clone's first checkout of Elyes's branch, use the same `--track origin/...` form. On later switches, use `git switch codex/civis-elyes`.

The scaffold serves health at `http://127.0.0.1:8001/health` and MCP at `http://127.0.0.1:8001/mcp`. Health says `ready: false` until the business implementation is delivered. Stop the process with Ctrl+C.

In VS Code, open the repository, run **Python: Select Interpreter**, and choose `brain/.venv/Scripts/python.exe`. All Python commands must use that environment. Do not regenerate packages just because an AI assistant suggests newer versions.

Alternatively, open `brain/civis.code-workspace` in VS Code for the preselected Windows interpreter and test settings. While the local scaffold is running, a second terminal in `brain/` can run `.\.venv\Scripts\python.exe scripts/smoke_scaffold.py` to check MCP version, authentication and the honest unimplemented responses. This script checks the initial scaffold, not a completed mock.

## Local configuration

Setup copies `.env.example` to the ignored `brain/.env` only if the file does not exist. It never overwrites an existing local configuration.

Meriem and Elyes: obtain a key at https://aistudio.google.com/apikey and edit `.env` locally: set `GEMINI_API_KEY` and, when implementing the adapter, `LLM_MODE=gemini`. Do not paste the key into an AI chat, commit, fixture, screenshot or PR. Fixture mode is for repeatable tests; it does not prove live AI integration.

Outbound `TWIN_BRAIN_KEY` must match the key Trinity configured for `city_brain`; `GUARDIAN_BRAIN_KEY` must match 9antra's Brain key. Incoming `BRAIN_TWIN_CALLER_KEY` and `BRAIN_GUARDIAN_CALLER_KEY` are separate keys for partners calling Brain. Example values are intentionally fake.

Guardian score/token tool names are explicitly unset until Elyes confirms them with Houssem. The connection adapter must refuse to start a joint workflow while those values are `CONFIRM_WITH_9ANTRA`.

## macOS/Linux equivalent

Install Git, VS Code and uv. In `brain/`: `uv venv --python 3.12 .venv`; `uv pip sync --python .venv/bin/python requirements-lock.txt`; `uv pip install --python .venv/bin/python --no-deps -e .`; copy `.env.example` to `.env` only if absent. Run `.venv/bin/python scripts/doctor.py`, then tests and the module. Scripts and fixtures must work on both platforms.

## Verified primary references

- uv installation: https://docs.astral.sh/uv/getting-started/installation/
- VS Code Python setup: https://code.visualstudio.com/docs/python/python-tutorial
- Official MCP SDK and mounting: https://py.sdk.modelcontextprotocol.io/run/asgi/
- Gemini API setup: https://ai.google.dev/gemini-api/docs/get-started
- Current free-tier pricing: https://ai.google.dev/gemini-api/docs/pricing
- Model code: https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite

Reference check: 7 October 2026. No live Gemini call has been made by this setup.
