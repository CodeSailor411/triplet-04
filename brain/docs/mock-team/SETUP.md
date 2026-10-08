# Windows setup for all four CIVIS members

All members use Windows 10/11, PowerShell, the same Python 3.12 environment and the same committed package lock. Scenario ownership changes the files you edit, not the software stack.

## 1. Install common software

Install Git, VS Code and uv. With Windows Package Manager:

~~~powershell
winget install --id Git.Git -e
winget install --id Microsoft.VisualStudioCode -e
winget install --id astral-sh.uv -e
~~~

Close and reopen PowerShell after installation. In VS Code install Microsoft's Python and Pylance extensions. Optional terminal method:

~~~powershell
code --install-extension ms-python.python
code --install-extension ms-python.vscode-pylance
~~~

Verify:

~~~powershell
git --version
uv --version
~~~

The setup script selects/downloads Python 3.12 through uv; no separate global Python installation is required. Use Git Credential Manager or VS Code to sign in with your own GitHub account and accept Elyes's repository invitation. Commit author configuration is separate from access.

No Docker, Node.js, React, database, GPU, local model, LangChain or CrewAI is required for the primary Brain mock. Optional GitHub Desktop is fine, but the commands below use PowerShell.

## 2. Clone once, then choose your branch

~~~powershell
git clone https://github.com/CodeSailor411/triplet-04.git
cd triplet-04
~~~

Run exactly your row on first checkout:

| Person | Command |
| --- | --- |
| Elyes | git switch --track origin/codex/civis-elyes |
| Yassine | git switch --track origin/codex/civis-yassine |
| Meriem | git switch --track origin/codex/civis-meriem |
| Maram | git switch --track origin/codex/civis-maram |

If this clone already has your branch, use git switch codex/civis-YOURNAME instead of creating it again. Confirm with git branch --show-current.

Existing clone with earlier setup: commit your work, ensure a clean tree, then fetch and merge the integration setup; do not clone over your existing folder or reset your commits:

~~~powershell
git fetch origin
git merge origin/codex/civis-elyes
~~~

## 3. Set your own commit identity

From repository root, replace both placeholders:

~~~powershell
git config user.name "YOUR_GITHUB_USERNAME"
git config user.email "YOUR_VERIFIED_EMAIL_OR_EXACT_GITHUB_NOREPLY_ADDRESS"
~~~

GitHub Settings > Emails shows your actual noreply address. Do not copy Elyes's name/email. Configuration applies to this clone; it does not grant write access.

## 4. Create and verify the environment

From repository root:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
~~~

Keep that PowerShell terminal in brain/ for Python commands. Use cd .. when running scoped Git staging from the root. Explicit interpreter paths avoid activation-policy/PATH confusion.

Setup creates brain/.venv, installs the locked modules, installs the editable package and creates ignored brain/.env only if absent. Existing .env values are preserved. Rerun setup after package-layout changes; members must not install independent dependencies.

In VS Code open brain/civis.code-workspace or select interpreter brain/.venv/Scripts/python.exe manually. Check the terminal interpreter with:

~~~powershell
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable); print(sys.version)"
~~~

## 5. Modules everyone receives

| Module | Pinned version | Use |
| --- | --- | --- |
| FastAPI | 0.142.2 | One Brain HTTP service |
| Uvicorn | 0.54.0 | Server process |
| Pydantic | 2.13.5 | Inputs/proposals/decisions |
| pydantic-settings | 2.15.0 | Local environment settings |
| Official MCP SDK | 2.3.0 | Shared server/client; protocol 2026-07-28 |
| httpx / httpx2 | 0.28.1 / 2.13.1 | HTTP tests/AI SDK and MCP transport |
| google-genai | 2.28.0 | Shared free Gemini adapter |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 | Unit and async workflow tests |
| Ruff | 0.16.10 | Lint checks |

requirements-lock.txt includes transitive dependencies. The lock remains pinned. jsonschema 4.26.0 is also declared directly for discovered request validation; it was already in the lock. Only Elyes approves dependency changes. Do not let an AI assistant regenerate the environment to fix a scenario bug.

| Person | Extra requirement | Focus |
| --- | --- | --- |
| Elyes | Own Google AI Studio key for shared adapter/live smoke; GitHub CLI optional | Common runtime, free API, MCP, auth, approvals, two small scenarios |
| Yassine | None beyond common setup; no API key needed | Traffic detector/response, JSON fixtures, pytest |
| Meriem | None beyond common setup; no API key needed | Water evidence/topology/preview rules, async response/tests |
| Maram | None beyond common setup; no API key needed | Medical event/carrier/destination/availability, async response/tests |

Each scenario uses an injected provider; it does not install another framework or create another network client. Coding-assistant accounts are separate from the runtime Gemini API. A member may use their own free API key for an optional live check, but it is not required for their scenario unit tests.

## 6. Local keys and shared connections

Default LLM_MODE=fixture is for repeatable tests. Elyes obtains a key at https://aistudio.google.com/apikey and edits ignored brain/.env locally. Set GEMINI_API_KEY and switch LLM_MODE=gemini for a live AI run. Configured model remains gemini-3.5-flash-lite; verify free-tier availability/access in the account before the live check. Quota/timeout is a blocked outcome; no paid fallback.

Do not paste real keys/tokens into an AI chat, fixture, screenshot, commit or PR. Fixtures and automated tests do not need credentials.

Outbound TWIN_BRAIN_KEY and GUARDIAN_BRAIN_KEY must match the keys supplied privately by Trinity/9antra. Incoming BRAIN_TWIN_CALLER_KEY and BRAIN_GUARDIAN_CALLER_KEY are separate caller keys. The committed example values are fake.

Guardian tool names remain CONFIRM_WITH_9ANTRA until confirmed. Shared code must not start a joint workflow with guessed mappings. Partner schemas, preview and caps are tracked in PARTNER_GAPS.md.

## 7. Start the partial Brain mock

From brain/:

~~~powershell
.\.venv\Scripts\python.exe -m civis_brain
~~~

Health: http://127.0.0.1:8001/health. MCP: http://127.0.0.1:8001/mcp. Readiness stays false until all five workflows and live checks pass. S03/S04 and shared tools work; relevant unfinished member inputs return SCENARIO_NOT_IMPLEMENTED. Ctrl+C stops the process.

A second PowerShell terminal in brain/ can check the initial transport:

~~~powershell
.\.venv\Scripts\python.exe scripts/smoke_mcp.py
~~~

This script starts and closes a temporary local fixture server and verifies real MCP negotiation, auth, Air Quality evaluation, read views and Guardian-only invalidation. It calls no external peer/API. See HANDOVER.md for four actual scenario replays and the separate live AI command.

## 8. Your first AI-assistant prompt

~~~text
Read brain/AGENTS.md, docs/mock-team/README.md, SETUP.md, CONTRACT.md, SCENARIOS.md and my task card. I use Windows and my assigned branch. Verify the interpreter and existing locked dependencies without reading .env or exposing secrets. Explain my allowed files and next step. Do not implement another person's work, change shared interfaces, upgrade dependencies or build the whole mock. Follow one step at a time and stop after showing its tests and diff.
~~~

Then use the separate prompt at each step of your own card. Read the explanation and verify actual test results before moving to the next step.

## Official references

- [uv installation, including WinGet](https://docs.astral.sh/uv/getting-started/installation/)
- [VS Code Python setup](https://code.visualstudio.com/docs/python/python-tutorial)
- [MCP SDK mounting](https://py.sdk.modelcontextprotocol.io/run/asgi/)
- [Gemini API setup](https://ai.google.dev/gemini-api/docs/get-started)
- [Gemini free-tier pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Configured model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)

Windows preparation checks run in GitHub Actions too. No live AI request has been made by this setup.
