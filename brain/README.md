# CIVIS Brain primary mock

Checkpoint **brain-mock-1**, 11 October 2026, on **codex/civis-elyes**: all five scenario modules are integrated. The three member submissions retain their merge history. This is an explicitly limited mock for partner testing. Full partner readiness remains false because the real Guardian contract, Traffic metric and Water preview still need partner work.

| Scenario | Original owner | Reduced mock response |
| --- | --- | --- |
| S01 Traffic | Yassine | Advertised R1 signal plan after persistent congestion |
| S02 Water | Meriem | Topology-supported R3 valve request, with required safe preview |
| S03 Power | Elyes | Evidence/uncertainty alert; no grid switching |
| S04 Air Quality | Elyes | Sustained PM2.5 alert; no actuator |
| S05 Medical | Maram | R2 ambulance dispatch to the reported destination |

One FastAPI/MCP service, one Gemini adapter and one shared validation/approval/execution path serve all five modules. See the [individual reviews and test evidence](docs/mock-team/INTEGRATION_REVIEW_2026-10-11.md), [handover](docs/mock-team/HANDOVER.md), [interface](INTERFACE.md) and [Windows setup](docs/mock-team/SETUP.md).

## Run on Windows

From the repository root:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
.\.venv\Scripts\python.exe scripts/doctor.py
.\.venv\Scripts\python.exe scripts/setup_peer_keys.py
.\.venv\Scripts\python.exe -m civis_brain
~~~

Open http://127.0.0.1:8001/. Select any of the five scenarios and its base/refusal case. **Recorded response** uses no external API; **Gemini API** makes a real planning request for Traffic, Water or Medical. The page always uses fake Twin and Guardian services, with editable standard readings, request/response traces and JSON export.

For an offline command-line replay, run:

~~~powershell
.\.venv\Scripts\python.exe scripts/run_case.py --scenario S01 --case base
~~~

Change S01 to S02-S05 and base to refusal as needed. Power and Air produce alerts with zero actuator effects and no Gemini call.

Health: /health. MCP: /mcp, protocol 2026-07-28. Caller keys are required for evaluation and read tools. Gemini and peer secrets stay in ignored .env. Logs use ignored run-logs/<run_id>.brain.jsonl; debug traces use .artifacts/. See [debugging](docs/mock-team/DEBUGGING.md) for controls and [partner gaps](docs/mock-team/PARTNER_GAPS.md) before a joint run.

Member PRs target codex/civis-elyes. Main and layer branches remain separate. Elyes authorized this limited checkpoint. Promotion into the brain layer branch still follows the agreed PR review flow; main is unchanged.
