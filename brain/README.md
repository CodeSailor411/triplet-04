# CIVIS Brain: five-scenario primary mock preparation

Windows environment, fixed scenario interfaces and four branches are prepared. Business logic remains assigned to the team and raises NotImplementedError; this setup is not a completed mock.

Start with the [meeting plan](docs/mock-team/README.md), [Windows setup](docs/mock-team/SETUP.md), [five scenarios](docs/mock-team/SCENARIOS.md) and [frozen contract](docs/mock-team/CONTRACT.md).

| Member | Scenario and responsibility | Branch |
| --- | --- | --- |
| Yassine | S01 persistent congestion | codex/civis-yassine |
| Meriem | S02 flood/high water | codex/civis-meriem |
| Maram | S05 medical emergency | codex/civis-maram |
| Elyes | S03 power, S04 air pollution, plus shared Gemini/peers/approval/runtime/reviews | codex/civis-elyes |

Each scenario owner writes the detector, bounded response, fixtures and tests inside their own domain folder. One shared Brain runtime handles all external communication. Member PRs target codex/civis-elyes; release goes to brain before 10 October 2026.

## Windows setup

From repo root after installing Git, VS Code and uv:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m civis_brain
~~~

Health: http://127.0.0.1:8001/health. MCP: http://127.0.0.1:8001/mcp. Current readiness is false and workflow tools return NOT_IMPLEMENTED. Passing preparation checks proves setup, not completed partner scenarios.

Python 3.12 and committed dependencies remain unchanged. Tests use recorded responses and fake peers without keys/network; Elyes implements the single free Gemini adapter and performs a separate live check. .env/.venv are ignored.

The [4 October checkpoint](docs/oct05/README.md) has eight incident rows; this plan selects five primary workflows. Secondary cross-domain actions and the remaining three incident types are deferred. [Partner gaps](docs/mock-team/PARTNER_GAPS.md) remain explicit, especially missing live water preview and Guardian schemas.
