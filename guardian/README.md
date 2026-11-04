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

## Guardian integration behavior

- Bearer-authenticated Twin SSE readings normalize into Guardian schemas; duplicate deliveries are ignored, conflicting content under the same reading ID is rejected, and skipped tick gaps are logged. Twin readings do not carry a signature field in `twin-mock-3`.
- `units_free` is scored deterministically by channel. Ambulance availability is represented as `channel=ambulance`, `unit=units`, and the Twin device/node IDs are retained. The supplied RF model has no `units_free` training feature, so its advisory is unavailable for this sensor.
- Guardian runs the bundled checks, reputation logic, deterministic trust scorer, and optional RF advisory. The supplied RF artifact and feature preprocessing remain unchanged; RF has zero numeric trust weight.
- Brain MCP exposes capability/advisory tools plus Guardian verdict and authorization tools. Brain MCP, API, Twin client, and Brain webhook use separate credentials.
- Guardian issues g1 Ed25519 tokens with action, targets, parameters, idempotency key, reading IDs, and key ID bound in claims. In the integration path, Twin discovery is required and token time comes from the discovered Twin clock; without it, issuance fails closed.
- A real in-process MCP 2.3.0 Streamable HTTP peer covers transport, Twin-shaped
  list-actions and clock results, structured/text-only replies, and SDK errors;
  the original canned-peer tests remain.
- Fresh verdicts use the evidence available at the reading's sequence and do not
  mutate reputation. Statistical drift reports `insufficient_history` until
  five prior readings exist, without adding a score penalty.
- S02 valve authorization is restricted to `set_valve_position`, Water/R3,
  `WAT-01`, and `position=40`. Guardian requires Twin's manifest to mark preview
  required and enforced. Brain makes the exact `preview_action` call; Twin
  applies its 60-tick, one-commit preview rule when Brain commits.
- S05 dispatch authorization requires Emergency/R2, the discovered dispatch
  carrier, one ambulance, and a medical incident node as destination. The token
  binds both the incident reading ID and the trusted ambulance `units_free`
  reading ID from that carrier. Guardian checks Twin's latest capacity before
  issuing the token, allowing a one-tick SSE race only when the reported unit
  count is unchanged.
- After a confirmed Twin containment effect, Guardian updates local trust state
  and calls Brain's `notify_containment` MCP tool. Twin containment calls use
  `isolate_sensor`, `quarantine_device`, `rollback_reading`, or `release_device`
  with the Twin-published arguments. The `twin-mock-3` tools have no
  `idempotency_key`; they document repeat-safe behavior.
- Twin's Ed25519 `g1` signature applies to Guardian action tokens, which Twin
  verifies with Guardian's configured public key. It is separate from Bearer
  authentication of the Twin SSE reading feed.

## Partner verification status

Guardian uses the `twin-mock-3` tool names and arguments from the supplied interface card. Local integration tests mock partner effects; they do not establish that a live Twin accepts the configured credentials or that a live Brain exposes a compatible `notify_containment` schema. Configure `BRAIN_MCP_URL` and `BRAIN_GUARDIAN_CALLER_KEY` for Brain containment notices. A confirmed Twin effect remains applied if Brain notification fails; Guardian returns and audits that notification status for retry/operations handling. See [INTERFACE.md](INTERFACE.md) for the message contracts and trust values.

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
| POST /isolate_sensor/{sensor_id}, /quarantine_device/{device_id} | Twin containment followed by Brain notification |
| POST /rollback_reading, /release_device/{device_id} | Twin rollback/release followed by Brain notification |
| POST /mcp | Brain-facing capability, advisory, verdict, and authorization tools |
| GET /api/capabilities | Capability, trust policy, action, and public-key metadata |

Protected routes require their corresponding bearer key when demo mode is off. Configure Guardian API, Brain MCP/webhook, and Twin credentials separately. `BRAIN_MCP_URL` plus `BRAIN_GUARDIAN_CALLER_KEY` enable outbound `notify_containment`; that key must equal Brain's configured `BRAIN_GUARDIAN_CALLER_KEY`. Brain receives `{"notice":{"event_id":"...","run_id":"...","state":"...","device_ids":[],"reading_ids":[]}}` only after Twin confirms the effect.

Reading signature requirements are server controlled with `GUARDIAN_REQUIRE_READING_SIGNATURES`; callers cannot set a per-reading `require_signature` switch. A supplied invalid signature is rejected even when signatures are not required. The Twin feed in `twin-mock-3` uses Bearer authentication and does not sign readings. Guardian's Ed25519 `g1` action-token verification is always mandatory.

## Verify

```powershell
\.venv\Scripts\python.exe -m pytest -q tests
```

The latest local run reports **81 passed, 2 skipped**. The skipped cases require
live Twin credentials. The clarified Guardian gate regressions report **12
passed**. This project snapshot has no separate live joint-gate runner, and
these local checks do not replace partner verification.


The service keeps readings, verdicts, and reputation in memory. The Random Forest was trained on synthetic data and is not a real-world security performance claim.
