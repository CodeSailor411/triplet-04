# Elyes implementation handover

Updated 9 October 2026. Integration branch: codex/civis-elyes.

## Completed

- S03: explicit mock overload candidate or an uncertainty warning; low load never asserts an outage. Default power thresholds remain disabled. No grid action.
- S04: PM2.5 candidate after two distinct consecutive ticks, with original historical evidence. Null, wrong unit/channel, duplicate tick and run reset are handled. No AQ actuator or inferred dispatch.
- Shared normalization, five-entry registry, separate run/scenario state, bounded evidence/decision cache, incident/explanation views and redacted JSONL.
- Reusable network-free Twin/Guardian/provider fixtures, four own scenario cases and one runner.
- Deterministic parameter/carrier/evidence/risk/topology checks, Guardian score and exact-command approval, required preview, all touched-domain caps, idempotency, refusal detail and optional pending confirmation.
- Direct Gemini Flash-Lite (gemini-3.5-flash-lite), using stateless Interactions and manifest-constrained JSON Plans. Selected evidence, a 60-second timeout, bounded output, no automatic retries and a per-run budget constrain calls. OpenRouter has been removed.
- Plain developer debug page at http://127.0.0.1:8001/: editable JSON requests, six presets, chronological model/peer requests and responses, decisions, simulated effects and a JSON export. Four presets exercise S03/S04; two exercise the shared action pipeline with a separate synthetic detector. Loopback checks, HttpOnly session cookie, same-origin POST and CSP protect the console. Set BRAIN_DEBUG_ENABLED=false to disable it.
- Authenticated MCP tools and Guardian-only evidence invalidation. Local HTTP/MCP smoke verified actual SDK negotiation, authorization, discovery and workflow.

The final five-scenario release is incomplete. Health/capabilities correctly return ready=false.

## Your next actions

1. Review Yassine, Meriem and Maram's PRs into codex/civis-elyes. No CIVIS member PR was open during this implementation check.
2. Ask Houssem for the actual Guardian tools, request/response schemas, numeric score scale, cut-offs, JWS claims and caller key. Configure the explicit adapter mapping after agreement.
3. Ask Dali for complete shared-domain cap discovery and the required water preview interface. Confirm pending/commit and the shared log format.
4. Your Gemini key is configured in ignored brain/.env with restricted Windows file access. Live Flash-Lite planning passed: the shared action demo committed one simulated effect, and its Guardian-refusal variant committed none. Follow [DEBUGGING.md](DEBUGGING.md) to inspect or edit requests. Power/Air cases require no AI call.
5. After member merges and live checks, complete the five-row acceptance matrix. Maram opens the release PR into brain; Elyes reviews it. Do not merge directly into main.

Containment lifecycle and overlapping requested-node counts remain partner discussion items. Brain does not settle them or call isolation, quarantine, release or rollback.

## Commands

From your working folder:

~~~powershell
Set-Location -LiteralPath 'C:\Users\thabe\Desktop\New folder (15)\triplet-04'
git branch --show-current
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
.\.venv\Scripts\python.exe scripts/run_case.py --scenario S03 --case base
.\.venv\Scripts\python.exe scripts/run_case.py --scenario S03 --case refusal
.\.venv\Scripts\python.exe scripts/run_case.py --scenario S04 --case base
.\.venv\Scripts\python.exe scripts/run_case.py --scenario S04 --case refusal
.\.venv\Scripts\python.exe scripts/smoke_mcp.py
.\.venv\Scripts\python.exe -m civis_brain
~~~

Use another PowerShell terminal for checks while the service runs. smoke_mcp.py starts and closes its own temporary local server; it does not inspect a running partner endpoint.

Live AI only, after your local key is configured:

~~~powershell
cd brain
.\.venv\Scripts\python.exe scripts/smoke_gemini.py
~~~

This sends one explicitly synthetic planning request. It calls no peer and executes no command. Missing key, quota or failure is reported honestly.

## Service modes and current limits

- Committed defaults are PEER_MODE=fixture and LLM_MODE=fixture. Your local .env selects Gemini while peers remain fixtures. Debug runs always use fresh fake Guardian/Twin instances. The browser shares a budget of three live AI calls per server session across scenario runs and the separate API connection check. Offline runs do not consume that budget.
- Installed Python is 3.12.13. All 55 applicable locked packages match; FastAPI/Pydantic/MCP/Uvicorn shared pins match Trinity's inspected requirements. The final decision report specifies Python/FastAPI and MCP protocol 2026-07-28, not exact package pins. See VERSIONS.md.
- Desktop and 390 px mobile browser checks passed with no JavaScript errors or horizontal overflow. Live success/refusal and all four offline S03/S04 cases passed. Editing the demo's high reading from 95 to 20 produced no incident, no AI call and no effect.
- Fixture service inputs use the supplied simulated clock, not a claim about Twin's live clock.
- PEER_MODE=live uses configured MCP URLs/keys and discovered schemas. Set GUARDIAN_CONTRACT_CONFIRMED=true only after confirming the explicit GUARDIAN_MAPPING_FILE.
- Fixture-only thresholds cannot authorize live workflows. Approved live policy and real evidence are required.
- TWIN_PREVIEW_TOOL and TWIN_COMMIT_TOOL have no assumed default. Required preview absent means blocked; unconfirmed execution remains pending.
- list_actions.action_cap supplies its own domain cap. A shared carrier also requires caps for its other domains; missing limits block.
- Twin must verify/consume the Guardian token. Brain checks exact JWS claims; it does not sign approvals or verify Twin's cryptographic implementation.
- Runtime retains 2,000 readings, 100 tick responses and 1,000 explanations per run. Duplicate accepted ticks do not repeat work. A changed accepted tick is blocked.
- Low-trust evidence gets at most three distinct-tick attempts, with no repeated same-tick score calls. There is no autonomous sleep/retry loop.
- An unchanged command keeps its run/scenario/action/targets/params idempotency key. Rejected receipts are not retried unchanged. Uncertain sends use the original key on a fresh evaluation.
- State and receipts are in memory. JSONL is an audit trace, not restart recovery. A restart requires a fresh run or explicit partner reconciliation before resuming uncertain physical operations.
- Containment invalidates queued evidence; release accepts new evidence and never restores old evidence. Already committed Twin effects are not undone.
- JSONL is a CIVIS mock format pending Trinity's final shared-log agreement. Do not describe the local transport test as completed live partner integration.

The synthetic action demo is shared-runtime evidence, not completion of Yassine's S01. Live Gemini success does not establish live Guardian/Twin integration. Local verification: 104 tests, Ruff, dependency checks and the actual local MCP transport smoke passed. No package upgrades were needed.
