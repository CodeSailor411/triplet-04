# Guardian integration runbook

This folder is the Guardian package root. Start the unified service from
PowerShell here. Partner URLs and credentials are environment configuration;
the repository contains no live partner endpoints or secrets.

## Local demo

```powershell
if (!(Test-Path '.venv\Scripts\python.exe')) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DEMO_MODE = 'true'
.\.venv\Scripts\python.exe .\src\run.py
```

Open `http://127.0.0.1:5000`. Demo mode explicitly bypasses authentication for
local mutation routes and must remain disabled for partner connections.

## Configured integration

Keep `DEMO_MODE` unset or set it to `false`. Set distinct keys for the inbound
Guardian API, inbound Brain MCP, outbound Twin client, and optional outbound
Brain webhook. Provision a persistent Ed25519 keypair separately; never put a
private key or bearer value in source control.

```powershell
$env:GUARDIAN_API_BEARER_KEY = 'guardian-api-key-issued-for-this-run'
$env:GUARDIAN_BRAIN_MCP_BEARER_KEY = 'brain-mcp-key-issued-for-this-run'
$env:TWIN_BASE_URL = 'https://twin-host-issued-for-this-run'
$env:GUARDIAN_TWIN_BEARER_KEY = 'twin-key-issued-for-guardian'
$env:GUARDIAN_TOKEN_PRIVATE_KEY = 'C:\secrets\guardian-ed25519-private.pem'
$env:GUARDIAN_TOKEN_PUBLIC_KEY = 'C:\secrets\guardian-ed25519-public.pem'
$env:GUARDIAN_TOKEN_KID = 'key-id-confirmed-with-twin'
.\.venv\Scripts\python.exe .\src\run.py
```

To consume the Twin SSE feed in another terminal:

```powershell
$env:TWIN_BASE_URL = 'https://twin-host-issued-for-this-run'
$env:GUARDIAN_TWIN_BEARER_KEY = 'twin-key-issued-for-guardian'
$env:GUARDIAN_API_BEARER_KEY = 'guardian-api-key-issued-for-this-run'
.\.venv\Scripts\python.exe .\src\twin_runner.py
```

If CIVIS confirms its webhook transport and payload, configure the optional
outbound Brain client with `BRAIN_VERDICT_URL` and
`GUARDIAN_BRAIN_BEARER_KEY`. These credentials are distinct from the inbound
Brain MCP key and Twin key. The HTTP webhook currently sends verdict summaries;
the Brain MCP endpoint handles verdict and authorization requests.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
```

Latest clean-venv full-suite result: **51 passed, 2 skipped**. The two live Twin
checks skip unless a configured partner is reachable. A small canned MCP peer
tests the Guardian discovery client; it does not emulate Twin behavior.

## Implementation status

### IMPLEMENTED AND TESTED LOCALLY

- Brain MCP verdict and authorization tools, advisory tools, separate bearer
  gates, and capability output with configured score policy and public token
  key metadata.
- Twin SSE normalization, duplicate replay handling, event ingestion, and
  structured Guardian audit records.
- Thin Twin MCP discovery client that lists tools and requests actions, clock,
  nodes, and containment state. Discovery is cached for the current run. A
  missing required tool or unavailable peer blocks authorization.
- Token issue and verify implementation with action, target, params, reading,
  idempotency, key ID, and clock binding.
- Config validation, local PowerShell runner, and baseline/fake-peer tests.

### PROPOSED / NOT YET JOINTLY TESTED

- Partner approval of all Twin and Brain tool names, request schemas, response
  schemas, protocol versions, and key registration.
- Safe-preview calls, Twin cap pre-check mapping, Twin containment calls,
  notification delivery, and Twin-side token verification.
- Live Twin SSE recovery/parity, real capacity semantics, reaction-time target,
  and any live Brain endpoint acceptance.
- Batch RF inference and the 109-reading-under-one-second benchmark.

Discovery placeholders are centralized in `src/guardian_config.py` and marked
`CONFIRM`. The local Power action cap and Telecom/Waste rollback pool sizes are
offline fallback values only. R3 and grid actions refuse until a safe preview
contract is confirmed and implemented.

## Open confirmations

- # CONFIRM with CIVIS: approve the Brain-facing MCP tool names in
  `src/contract.py` and their structured input/output schemas.
- # CONFIRM with Twin: confirm `list_actions`, `get_clock`, `list_nodes`, and
  `get_containment_state` names and schemas used by `src/guardian_config.py`.
- # CONFIRM with Twin: safe-preview tool name/schema, preview validity, and
  preview ID binding required by R3 and grid actions.
- # CONFIRM with Twin: isolate, quarantine, rollback, and release tool names and
  schemas, idempotency behavior, refusal codes, and containment-state response.
- # CONFIRM with CIVIS: containment notification transport, payload,
  authentication, retry, and acknowledgment contract.
- # CONFIRM with policy owners: final Trusted and Degraded cut-offs and minimum
  scores for R1, R2, and R3. Current values are provisional; see
  `G7_NUMBERS.md`.
- # CONFIRM with Twin/CIVIS: Telecom and Waste sensor names, units, node
  identifiers, action risk tiers, and minimally safe Guardian mappings.
- # CONFIRM with Twin/CIVIS: token audience, key ID registration, simulated
  clock schema, signature verification, and distributed one-time-use contract.
- # CONFIRM with Twin: capacity response schema and shared-node accounting rules
  for per-domain action caps, containment, and rollback pools.
- # CONFIRM with Twin/CIVIS: pushed-score feed schema, numeric scale, and
  whether Guardian should publish scores independently of verdict requests.
