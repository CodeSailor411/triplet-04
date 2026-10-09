# Local Brain debugging

Open PowerShell in your checkout's brain folder and start the service:

~~~powershell
.\.venv\Scripts\python.exe -m civis_brain
~~~

Open http://127.0.0.1:8001/. If the service is already running, use that page. After changing Python code or .env, stop your running server with Ctrl+C and start it again.

## Run the complete action workflow

1. Select **Shared action demo (synthetic detector): base**.
2. Select **Gemini API** and load the preset if necessary. Check that the request JSON has "provider_mode": "gemini".
3. Press **Run request**. This submits the editable JSON to /debug/run.
4. Tick 1 is a baseline. Tick 2 detects the mock incident, requests a Gemini Plan, validates it, requests mock Guardian approval and sends the approved command to mock Twin. The expected result is **committed**, **1 AI call**, **1 simulated effect**.
5. Expand the request/response entries to inspect selected evidence, the actual Gemini request and final JSON, approval, actuation and receipts. **Download this debug run as JSON** exports the trace.

The live base and refusal flows passed on 9 October 2026 using gemini-3.5-flash-lite. Live AI can still fail because of network, quota or output validation; the page reports the failure rather than treating it as a successful fixture run.

## Cases and expected results

| Preset | What it checks | Expected |
| --- | --- | --- |
| Shared action demo: base | Complete action pipeline | One committed simulated effect |
| Shared action demo: refusal | Mock Guardian denies the proposed command | Blocked, GUARDIAN_DENIED, zero effects |
| Power: base | Explicit mock overload candidate | Alert, zero effects |
| Power: refusal | Evidence does not establish the claimed power fault | Uncertainty alert, zero effects |
| Air Quality: base | Sustained PM2.5 evidence | Alert, zero effects |
| Air Quality: refusal | Invalid or insufficient pollution evidence | Warning, zero effects |

Power and Air Quality are Elyes's actual alert-only modules. They do not need Gemini even when Gemini is selected. The shared action demo uses a separate synthetic detector and does not complete or replace Yassine's S01. Guardian and Twin are fake peers in every debug run.

Select **Recorded response (offline)** to run the same pipeline using a saved Plan and no external AI request. Each run starts with fresh mock state; it does not modify another run or the active service workflow.

## Edit the input

The editor contains the complete request body, including its readings. Run sends exactly that JSON. Reloading a preset replaces the editor contents.

For a simple check, load the shared action base and change the second congestion value from **95** to **20**, leaving its IDs, timestamps and other fields intact. Run it again. Both readings are now below the fixture threshold of 80, so the expected result is **no incident, no AI call, no effect**. Edited inputs are marked as custom; the original preset's pass/fail result is not applied to them.

Use the preset structure: one run_id per request, increasing ticks and UTC timestamps, distinct source reading IDs, known node IDs, and the metric's declared unit/channel. Preserve null when a value or channel is absent. Invalid input produces validation errors or a blocked/warning result; the runtime does not invent missing evidence.

The displayed mock configuration shows nodes, actions, policy, caps and Guardian settings. These fixed fixture values are test assumptions, not new agreements with Trinity or 9antra. This editor changes readings, not discovery or policy.

## Gemini and environment

Your local .env selects:

~~~dotenv
LLM_MODE=gemini
GEMINI_MODEL=gemini-3.5-flash-lite
AI_TIMEOUT_SECONDS=60
PEER_MODE=fixture
~~~

GEMINI_API_KEY is stored only in your local ignored .env. The console shows whether it is configured, never its value. OpenRouter is no longer used.

The pinned Google SDK calls Interactions with a structured JSON schema, store=false, low thinking and a 2,048-token output limit. Requests contain selected fixture evidence; search tools are not enabled. The console displays the final answer, not internal model reasoning.

The browser permits **three live AI calls per server session**, shared by scenario runs and the separate API-only check. Restarting the service resets this local budget. Offline cases are unlimited. The separate API-only button checks Gemini but does not run Guardian/Twin or produce an effect.

Python remains 3.12.13 with the committed dependency lock. No package upgrades are required. See [SETUP.md](SETUP.md) for installation and [VERSIONS.md](VERSIONS.md) for compatibility evidence.

## Verification

104 local tests, Ruff, dependency checks and the local MCP transport smoke passed. Browser checks covered live Gemini approval/refusal, all four offline Power/Air cases, edited baseline readings, and desktop/mobile layouts.

The latest exported trace is saved under ignored .artifacts/debug/last-run.json. This checkout also retains the verified live examples as live-gemini-base.json and live-gemini-refusal.json in that directory. Exported keys/tokens are redacted.

This verifies Brain with real Gemini and fake partner services. Live Guardian/Twin integration and the three teammates' scenario implementations are still pending.
