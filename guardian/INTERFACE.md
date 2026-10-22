# Guardian integration interface

Guardian Unified runs at `http://127.0.0.1:5000` by default. Its local `/mcp` endpoint is the **model advisory** server. Twin connections are separate: configure `TWIN_BASE_URL` and `GUARDIAN_TWIN_BEARER_KEY`; the Twin adapter connects to `/events` and `/mcp`. Twin credentials and credentials for Brain callers are separate. Set `GUARDIAN_API_BEARER_KEY` to protect Guardian's incoming integration endpoints. Configuration is loaded from process environment; `guardian/.env.example` is a placeholder reference, not automatically loaded.

## Twin SSE and Guardian ingestion

The Twin's documented `readings` event envelope is `{"run_id":"...","readings":[...]}`. Guardian's bridge command consumes SSE and posts each envelope to `POST /api/integrations/twin/event` with Guardian's API key. `hello` and `heartbeat` are ignored. The client applies bounded exponential reconnect (maximum configured attempts) and reports rejected credentials, malformed JSON, and exhausted retries. It does not infer missed ticks after reconnection.

```json
{"event":"readings","data":{"run_id":"run-42","readings":[{
  "run_id":"run-42","reading_id":"read-17","device_id":"PWR-01-load",
  "node_id":"PWR-01","timestamp":"2026-10-22T12:00:00Z","tick":17,
  "sensor":"load_kw","channel":null,"value":450,"unit":"kW","lat":36.5,"lon":11.5
}]}}
```

The adapter currently maps Twin `congestion_index`, `water_level`, `load_kw`, `pm25`, and `emergency_calls` to Guardian sensor types. Missing/unknown sensors or null values fail validation; this project does not yet have Telecom/Waste scoring feature semantics. Guardian uses `lng` internally but maps Twin `lon`. Accepted Twin readings produce the ordinary Guardian score/verdict and a JSONL evaluation trace.

The incoming ingestion request requires:

```http
Authorization: Bearer <GUARDIAN_API_BEARER_KEY>
```

Without configured Guardian API key, integration endpoints fail closed with HTTP 503. Invalid or absent key returns 401. `POST /ingest` remains the legacy local demo endpoint. Incoming API key is distinct from the Twin outbound Bearer key.

## Authorization and token verification

`POST /api/actions/authorize` requires the API Bearer key and an existing Guardian verdict identified by `reading_id`. Example request:

```json
{"run_id":"run-42","reading_id":"read-17","action":"set_grid_switch",
 "parameters":{"state":"open"},"risk_level":"NONE","domain":"Power"}
```

Guardian normalizes aliases before allowlist checks, risk checks, cap enforcement, and token signing. Approval returns `decision`, normalized `action`, `token_id`, `expires_at`, and a signed `token`. Denials return no token and write an audit record. `POST /api/actions/verify` accepts `{ "token":"...", "action":"...", "parameters":{} }`; successful verification consumes the token once.

Token wire format is `g1.<base64url(canonical UTF-8 JSON claims)>.<base64url(Ed25519 signature)>`; signature input is the ASCII bytes `g1.<payload-segment>`. Claims are sorted-key compact JSON and include `v`, `token_id`, `iss`, `aud`, `run_id`, normalized `action`, canonical `parameters`, `iat`, `exp`, `reading_id`, `trust_score`, and `risk_level`. `exp - iat` is exactly 60 seconds. The token service accepts an injectable clock; default is Unix time until the Twin simulated-clock contract is connected. Twin cross-verification has **not** been run. Private PEM key path is `GUARDIAN_TOKEN_PRIVATE_KEY`; public key path is `GUARDIAN_TOKEN_PUBLIC_KEY`. Generate a persistent pair with `python guardian/src/generate_token_keys.py --private <private.pem> --public <public.pem>`. Never commit the private key; distribute the public PEM to Twin through the agreed channel.

## Trust policy and resource limits

The scorer's numeric field is `trust_score`. Defaults preserve existing code: `>0.7` trusted, `>0.3` through `0.7` suspect, and `<=0.3` compromised. Policy lives in `src/guardian_policy.json`; boundaries are strict as stated. It classifies readings separately from actuator permissions. Risk minima R1 `0.50`, R2 `0.70`, R3 `0.85` come from the meeting's noted placeholders, and are marked provisional. An older README proposed R3 `0.75`; partner confirmation remains required. Core action tiers follow the Twin sensor-table v1.3 (signal R1, dispatch R2, valve R3); Power grid switch is untiered. Telecom/Waste proposals do not assign risks, so those actions are currently fail-closed until CIVIS/Twin confirms the required tier.

Action aliases are centralized: `set_failover` → `set_priority_mode`; `set_collection_priority` → `send_collection_truck`. Unknown actions fail closed. The Twin's sensor table assigns R1 to `set_signal_plan`, R2 to `dispatch`, R3 to `set_valve_position`, and no risk tier to `set_grid_switch`. Telecom/Waste proposal does not assign risk levels, so those mapped actions are fail-closed pending CIVIS/Twin confirmation. Power's untiered action requires a `trusted` Guardian classification. Power action cap is 3 per run, counting successful Guardian authorization attempts across Power actuator actions. `POST /api/actions/rollback-pool/{domain}/{node_id}` requires a known Guardian `reading_id` and Bearer key. Telecom and Waste rollback reservation pools each hold 3 unique node IDs; repeated reservation of an occupied node is idempotent, release frees one slot. These limits are Guardian-side policy bookkeeping, not evidence Twin executed a rollback or actuator command. Twin's registry and capacity enforcement remain remote.

## Audit and commands

Every evaluated Twin reading and action decision appends one JSON record to `run-logs/<run_id>.guardian.jsonl` by default (override with `GUARDIAN_AUDIT_DIR`). Reading-derived records have `caused_by` set to the reading ID. Approvals include `data.token_id`; full tokens, signatures, bearer keys, and private keys are excluded/redacted. In-memory replay protection lasts for the process lifetime; use a persistent shared replay store for multi-worker deployments.

```powershell
# Unit tests (policy, token, audit, adapters)
.\.venv\Scripts\python.exe -m pytest -q guardian\tests\test_guardian_integrations.py guardian\tests\test_mcp_advisory.py

# Local deterministic pipeline tests
.\.venv\Scripts\python.exe -m pytest -q guardian\tests\test_unified_integration.py

# Configured external Twin smoke tests; explicitly skips when credentials are absent
.\.venv\Scripts\python.exe -m pytest -q guardian\tests\test_twin_live.py

# Full suite
.\.venv\Scripts\python.exe -m pytest -q guardian\tests

# Brain verdict webhook, retries, and outbox recovery only
.\.venv\Scripts\python.exe -m pytest -q guardian\tests\test_brain_client.py

# Start Guardian (another terminal)
.\.venv\Scripts\python.exe .\guardian\src\run.py

# Consume the configured real Twin event stream and feed this Guardian instance
.\.venv\Scripts\python.exe .\guardian\src\twin_runner.py

# One-off Twin MCP tool call
.\.venv\Scripts\python.exe .\guardian\src\twin_runner.py --tool get_clock --arguments '{}'
```

The SSE JSON envelope, reconnect/resume semantics, event auth, Twin MCP schemas, simulated clock, action registry, and Twin token verification are documented by partner notes but have not been verified against a live Twin. No live Twin/Brain connection was available during this implementation.

## Guardian verdict delivery to Brain

`src/twin_runner.py` can optionally forward each Twin reading evaluation with a Guardian verdict to a Brain HTTP webhook. Configure both `BRAIN_VERDICT_URL` and `GUARDIAN_BRAIN_BEARER_KEY` in the environment of the runner. The endpoint must be HTTPS except for loopback-only local testing. The Brain key is separate from `GUARDIAN_API_BEARER_KEY` and `GUARDIAN_TWIN_BEARER_KEY`. If neither Brain variable is set, verdict delivery is disabled; setting only one is a configuration error.

The runner sends an authenticated `POST` with `Content-Type: application/json` and a stable `Idempotency-Key` (SHA-256 of `run_id:reading_id`). The body uses the versioned `guardian.verdict.v1` shape:

```json
{
  "schema_version": "guardian.verdict.v1",
  "event_id": "sha256-hex-idempotency-key",
  "run_id": "run-42",
  "reading_id": "read-17",
  "sensor_id": "PWR-01-load",
  "timestamp": 1792670400,
  "verdict": "trusted",
  "trust_score": 0.91,
  "reasons": [],
  "city_brain": {
    "status": "allowed",
    "allowed": true,
    "action": "consume_reading",
    "reason": "guardian_policy_satisfied",
    "simulated_only": true
  },
  "model_advisory": {
    "label": "Trusted",
    "probability": 0.03,
    "model_version": "0.2.0-synthetic-demo",
    "advisory_only": true
  }
}
```

The Brain team must accept this schema or agree on a mapping before production use. This webhook sends verdict information only; it does not claim that the simulated City Brain action was executed. Security-gate rejections without a Guardian score are not labeled as verdicts and are skipped by this webhook; their rejection remains in the Twin ingestion response.

Transient network failures and HTTP 408, 429, and 5xx responses are retried with bounded exponential backoff. Other non-2xx responses (including 401/403) fail immediately. Before attempting delivery, each verdict is persisted in the append-only `GUARDIAN_BRAIN_OUTBOX` JSONL file (default `run-logs/brain-outbox.jsonl`). Failed entries remain pending; the runner stops with an error and will retry pending entries on its next start. A 2xx response marks an entry delivered. The Brain endpoint should honor `Idempotency-Key` to avoid duplicate processing if a crash occurs between Brain acceptance and local acknowledgment. Outbox entries contain only the verdict summary and advisory, not raw readings, coordinates, or credentials. Rotate/archive the outbox under the deployment's retention policy.

Additional optional variables are `BRAIN_TIMEOUT_SECONDS` (default 10, range `(0,120]`), `BRAIN_MAX_RETRIES` (default 3, range `[0,10]`), `BRAIN_RETRY_BASE_SECONDS` (default 0.5, range `[0,10]`), and `GUARDIAN_BRAIN_OUTBOX`. The endpoint, bearer credential, payload mapping, and delivery behavior have local tests; a real partner Brain endpoint, authentication credential, acknowledgment semantics, and schema acceptance still require partner validation.
