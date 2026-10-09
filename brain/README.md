# CIVIS Brain primary mock

Elyes's S03 Power and S04 Air Quality scenarios and the shared Brain runtime are implemented. S01 Traffic, S02 Water and S05 Medical remain with their owners. Full-release readiness is false.

| Member | Work | Branch |
| --- | --- | --- |
| Elyes | Power, Air Quality, shared runtime, Gemini, peers, approval, MCP, tests/review | codex/civis-elyes |
| Yassine | S01 congestion | codex/civis-yassine |
| Meriem | S02 high water | codex/civis-meriem |
| Maram | S05 medical dispatch | codex/civis-maram |

Start with the [handover](docs/mock-team/HANDOVER.md), [Windows setup](docs/mock-team/SETUP.md) and [contract](docs/mock-team/CONTRACT.md).

## Windows

From the repository root:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
.\.venv\Scripts\python.exe scripts/run_case.py --scenario S03 --case base
.\.venv\Scripts\python.exe scripts/run_case.py --scenario S04 --case base
.\.venv\Scripts\python.exe scripts/smoke_mcp.py
.\.venv\Scripts\python.exe -m civis_brain
~~~

Debug console: http://127.0.0.1:8001/. Replay Power/Air cases, inspect evidence and decisions, or explicitly test the AI connection. Keys stay on the server. Health: http://127.0.0.1:8001/health. MCP: http://127.0.0.1:8001/mcp, protocol 2026-07-28. Ctrl+C stops the service.

Defaults use local fixture peers and recorded AI responses. The service fixture recognizes AQ-01 and POW-01. Case replay loads its own nodes, clock, policies and fake peers. Base/refusal Power and Air cases produce recorded alerts with zero provider calls and actuator effects. Unsupported member scenarios return SCENARIO_NOT_IMPLEMENTED when relevant data arrives.

The shared core validates discovery, clock, evidence, parameters, risk, topology, preview, exact approval and per-domain caps. Only Twin executes. Guardian-only containment notices invalidate evidence; Brain performs no containment. Tests with synthetic candidates prove shared R1/R2/R3 safeguards, not completion of member detectors.

The live adapter uses direct Gemini Interactions with gemini-3.5-flash-lite. Configure GEMINI_API_KEY and LLM_MODE=gemini in ignored .env. The debug page includes editable standardized ReadingsBatch requests, full peer/AI request and response traces, acceptance checks and JSON export. Power/Air run their real detectors; the separate synthetic signal demo exercises Gemini, shared validation, mock Guardian approval and mock Twin execution. It is not completion of the assigned Traffic scenario. See [debug instructions](docs/mock-team/DEBUGGING.md) and [version verification](docs/mock-team/VERSIONS.md).

Members refresh their own clean branch from origin/codex/civis-elyes, implement only their assigned paths and PR into codex/civis-elyes. Main and the layer branches are not changed by this implementation. Review [partner gaps](docs/mock-team/PARTNER_GAPS.md) before a joint live run.
