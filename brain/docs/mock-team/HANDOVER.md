# CIVIS primary mock handover

Updated 11 October 2026. Integration branch: **codex/civis-elyes**. Checkpoint: **brain-mock-1**, authorized by Elyes as a limited mock. All five modules are integrated. Main and member branches were not modified. The published Twin source was imported unchanged into the local twin/ folder.

## What runs

- Traffic: persistent congestion in percent, R1 signal command, complete source evidence and exact authorization.
- Water: high-water candidate in cm, supplied safe valve choice, R3 preview before approval and actuation.
- Power: explicit evidence/uncertainty alert. No invented outage or grid switching.
- Air Quality: sustained PM2.5 in ug/m3, alert only.
- Medical: calls/min on medical channel, whole ambulance units on ambulance channel, R2 dispatch with carrier targets and separate destination.

All modules use the same normalization, registry, Gemini provider, manifest validator, Guardian approval and Twin execution path. The developer page offers ten presets: base/refusal for each of the five scenarios. See [DEBUGGING.md](DEBUGGING.md).

## Verification and limits

The [review report](INTEGRATION_REVIEW_2026-10-11.md) records individual defects and corrections. Latest [handover audit](HANDOVER_AUDIT_2026-10-11.md): 280 automated tests, Ruff, all 55 applicable dependency pins, three-server authenticated MCP tests, and real Gemini planning for S01/S02/S05.

Current Twin main at 9170ee2 was tested over real MCP using its actual code, synthetic readings and a test Guardian. Medical approval committed once; denial committed nothing. Water returned PREVIEW_UNAVAILABLE. Traffic's current speed/count readings produced an explicit missing-metric alert. Twin's actual log merger accepted Brain part files. This does not verify the real 9antra implementation.

Python is 3.12.13. The lock was not upgraded. Public /health and get_capabilities retain ready=false for full partner readiness even though all five local modules are implemented.

## Start and demonstrate

From brain/:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
.\.venv\Scripts\python.exe scripts/doctor.py
.\.venv\Scripts\python.exe -m civis_brain
~~~

Open http://127.0.0.1:8001/. Start with Recorded response. Traffic, Water and Medical base cases each commit one simulated effect. Their refusal cases commit none. Power/Air cases produce alerts. Select Gemini API to inspect a real model request with the same fake partner workflow.

Offline CLI: .\.venv\Scripts\python.exe scripts/run_case.py --scenario S01 --case base. All S01-S05 base/refusal cases work. scripts/smoke_mcp.py tests transport with temporary local servers.

An optional local Twin checkout can be tested with scripts/smoke_partner_twin.py --twin-root <path-to-twin-folder>. Install that Twin's declared dependencies separately and supply --extra-deps if needed; do not add Twin-only packages to Brain's lock. The check freezes Twin's clock and uses explicit synthetic test policy in temporary servers.

## Operating boundaries

- Committed defaults use fixture peers and recorded responses. Local .env may select Gemini; the debug page always creates fresh fake peers. Three live AI calls are allowed per server session; restart the service to reset this local budget.
- Live partner mode requires approved policy, real endpoints/keys and confirmed Guardian mapping. Fixture-only policy cannot authorize live actions.
- The Brain's caller supplies a ReadingsBatch through evaluate_tick. Twin does not currently push batches automatically; a driver must fetch get_readings and call Brain.
- Tokens bind the exact command, use RFC3339 simulated UTC iat/exp, normalized score 0..1 and a maximum 60 simulated seconds. Twin is responsible for cryptographic verification and execution. Brain never creates real approvals.
- Brain polls get_containment_state before detection and execution, and accepts Guardian-only invalidation callbacks. Release permits new evidence; invalidated readings stay invalid. Brain never contains or releases devices.
- Every touched domain needs an advertised cap. Refusals retain detail and cause no partial effect. Unchanged rejected commands are not resubmitted; uncertain outcomes retain the original idempotency key.
- Optional pending confirmation works only when advertised and configured. No premature commit is recorded. A pending deadline and the meeting's full retry sequence are not yet implemented.
- State is in memory: 2,000 readings, 100 tick responses and 1,000 explanations per run. Logs are audit evidence, not crash recovery. Restart with a fresh run ID or reconcile uncertain execution first.
- Per-run JSONL follows the 9 October envelope; secrets/tokens/hidden truth are redacted. Disk failures retain in-memory outcomes and report LOG_WRITE_FAILED without misreporting a committed action.

## Before full joint acceptance

1. Elyes explicitly authorized publishing this limited mock while full interoperability remains unverified. Keep ready=false until the following joint checks pass.
2. Confirm Houssem's real Guardian schema, score scale/cut-offs, exact-token request including simulated time, keys and errors; run the joint smoke test.
3. Resolve the missing Traffic metric/conversion and Water preview with Dali.
4. Agree the architecture's real/simulated timeout numbers and pending/retry behavior. Current 60-second AI timeout does not guarantee the Phase 1 ten-second reaction target.
5. The meeting mentions human escalation; the current user-approved scope explicitly excludes human review. Resolve that scope difference with the team before claiming full meeting compliance.
6. Promotion into the brain layer branch follows the agreed PR route after partner review. This checkpoint does not merge into main.

For exact credential directions, Guardian payloads, optional mapping fields and token standards, see [GUARDIAN_CONTRACT.md](GUARDIAN_CONTRACT.md).
