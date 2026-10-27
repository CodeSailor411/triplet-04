# Guardian (9antra)

Guardian's architecture role is **trust, authorization, and containment**. It consumes Twin's independent sensor evidence, computes deterministic trust scores, checks proposed action intent and risk, and signs authorization tokens. Brain plans and requests authorization; Twin executes actions and enforces its own caps. Guardian scores are evidence and never replace tokens. The Random Forest output is advisory and has zero numeric weight in Guardian trust.

## Run locally

PowerShell, from this project root:

```powershell
if (!(Test-Path '.venv\Scripts\python.exe')) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r .\src\requirements.txt
$env:DEMO_MODE = 'true'
.\.venv\Scripts\python.exe .\src\run.py
```

Open <http://127.0.0.1:5000>. Demo mode is for local use and bypasses authentication on protected routes. It is off by default. Live partner integrations have not been jointly tested.

## Implemented and tested locally

- Twin SSE readings normalize into the Guardian schema; duplicate deliveries are ignored, conflicting content under the same reading ID is rejected, and skipped tick gaps are logged.
- Guardian runs the bundled checks, reputation logic, deterministic trust scorer, and optional RF advisory. The supplied RF artifact and feature preprocessing remain unchanged; RF has zero numeric trust weight.
- Brain MCP exposes capability/advisory tools plus Guardian verdict and authorization tools. Brain MCP, API, Twin client, and Brain webhook use separate credentials.
- Guardian issues g1 Ed25519 tokens with action, targets, parameters, idempotency key, reading IDs, and key ID bound in claims. In the integration path, Twin discovery is required and token time comes from the discovered Twin clock; without it, issuance fails closed.
- A real in-process MCP 2.3.0 Streamable HTTP peer covers transport, Twin-shaped
  list-actions and clock results, structured/text-only replies, and SDK errors;
  the original canned-peer tests remain.
- Fresh verdicts use the evidence available at the reading's sequence and do not
  mutate reputation. Statistical drift reports `insufficient_history` until
  five prior readings exist, without adding a score penalty.
- Isolate and quarantine routes are **LOCAL SIMULATION ONLY**. They change
  in-memory Guardian state and never call Twin or perform real containment.
- The latest local full-suite run reports **69 passed, 2 skipped**. The skipped
  tests require a live Twin connection; local in-process coverage is not partner
  verification.

## Proposed or not jointly tested

Twin MCP tool names and schemas remain unconfirmed. Discovery is a thin client using explicitly marked placeholders. Authorization refuses if required discovery is unavailable. Safe preview and Twin-side containment calls are not implemented; R3/grid authorization is therefore refused. Capacity parsing accepts only an explicitly recognized response shape and is advisory; Twin remains authoritative. Local Power/rollback limits are labeled offline fallbacks.

No live Twin feed, preview, containment action, token verification by Twin, or Brain endpoint has been jointly validated. No code here implements Twin or Brain behavior. See [INTERFACE.md](INTERFACE.md) for the Guardian message contracts and provisional trust values.

## Trust policy

Current configured values are Trusted at score >= 0.7, Degraded at > 0.3 and < 0.7, and Untrusted at <= 0.3. Provisional action minima are R1 0.5, R2 0.7, and R3 0.85. These settings can be overridden with the GUARDIAN_TRUSTED_MIN, GUARDIAN_DEGRADED_MIN, and GUARDIAN_R1_MIN_SCORE / GUARDIAN_R2_MIN_SCORE / GUARDIAN_R3_MIN_SCORE environment variables; startup validation requires R2 and R3 at or above the Trusted cutoff.

A synthetic Twin-shaped water sequence ending at 180 cm scored 0.75 on its focus reading, 0.10 below the provisional R3 minimum. This is one local synthetic check, not a live Twin result or a maximum reachable score; the threshold was not lowered.

## Main integration routes

| Route | Purpose |
|---|---|
| GET /health | Service and model readiness |
| POST /api/integrations/twin/event | Authenticated Twin reading ingestion |
| POST /api/actions/authorize | Fresh-verdict policy check and token issue/refusal |
| POST /api/actions/verify | Local one-time token verification for testing |
| POST /mcp | Brain-facing capability, advisory, verdict, and authorization tools |
| GET /api/capabilities | Capability, trust policy, action, and public-key metadata |

Protected routes require their corresponding bearer key when demo mode is off. Configure the Guardian API, Brain MCP, and Twin credentials separately.

## Verify

```powershell
\.venv\Scripts\python.exe -m pytest -q tests
```


The service keeps readings, verdicts, and reputation in memory. The Random Forest was trained on synthetic data and is not a real-world security performance claim.
