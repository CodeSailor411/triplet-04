# CIVIS Brain mock interface

Revision: 11 October 2026. Python 3.12; FastAPI; MCP Streamable HTTP, protocol 2026-07-28. Start from brain/ with .\.venv\Scripts\python.exe -m civis_brain. MCP endpoint: http://127.0.0.1:8001/mcp. Local developer console: http://127.0.0.1:8001/.

| MCP tool | Arguments | Caller/result |
| --- | --- | --- |
| get_capabilities | {} | Public discovery, implemented tools and readiness |
| evaluate_tick | {batch: ReadingsBatch} | Twin, Guardian or scenario caller; returns DecisionBatch |
| get_active_incidents | {run_id: string} | Authenticated caller; active candidates for that run |
| explain_decision | {decision_id: string} | Authenticated caller; saved decision or found=false |
| notify_containment | {notice: ContainmentNotice} | Guardian only; invalidates affected evidence |

Use distinct Bearer keys configured in ignored .env: BRAIN_TWIN_CALLER_KEY, BRAIN_GUARDIAN_CALLER_KEY and BRAIN_SCENARIO_KEY. Local development defaults are not partner credentials.

**Batch:** run_id, tick, time (RFC3339 UTC), tick_seconds, count, readings. Each reading keeps run_id, reading_id, tick, timestamp, node_id, device_id, sensor, channel, value and unit. Null remains null. Membership comes from list_nodes. Extra future fields are tolerated; malformed required fields are rejected.

**Flow:** a driver gets Twin readings and calls evaluate_tick. Brain discovers nodes/actions/clock/containment, detects candidates, obtains Guardian evidence assessments, asks Gemini for an actionable Plan, validates it, previews R3, requests exact approval, rechecks containment/clock and calls Twin actuate. Twin alone executes. Current Twin does not automatically send batches.

**Responses:** alert, blocked, pending, committed or rejected, with evidence IDs and reasons/codes. Pending is not a completed action. explain_decision is a read tool; it does not rerun anything.

**Local presets:** Traffic percent -> R1 signal; Water cm -> R3 valve with supported topology/preview; Power kW/V -> alert; Air Quality ug/m3 -> alert; Medical calls/min plus ambulance units -> R2 dispatch. All are synthetic test readings. CLI scripts/run_case.py supports S01-S05 base/refusal. BRAIN_FIXTURE_CASE selects the fixture discovery/profile for the long-lived MCP service, e.g. mocks/cases/traffic/base_case.json; restart after changing it. Debug replays load their own case without altering that service.

**Live boundaries:** real Guardian mapping is unverified; current Twin lacks Traffic congestion_index and Water preview. Illustrative policy is blocked with live peers. Timeouts/retry/pending deadlines still need team agreement. ready=false describes those partner gaps, not missing local scenario modules.

**Logs:** run-logs/<run_id>.brain.jsonl, meeting envelope with event_id, timestamp, tick, wall, layer, event_type, caused_by and data; decisions include idempotency_key. Secrets and full tokens are redacted. In-memory state requires a new run after restart.

See [review evidence](docs/mock-team/INTEGRATION_REVIEW_2026-10-11.md) and [handover](docs/mock-team/HANDOVER.md). Checkpoint: brain-mock-1, an explicitly limited mock; full joint readiness remains false.

Latest checks and release limits: [handover audit](docs/mock-team/HANDOVER_AUDIT_2026-10-11.md). Guardian field mapping and credentials: [contract](docs/mock-team/GUARDIAN_CONTRACT.md).
