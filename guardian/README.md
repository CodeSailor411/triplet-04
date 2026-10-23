# TSYP14 Guardian Layer Convergence Mock

One local demonstration app connects the Guardian Layer checks, the supplied Random Forest advisory, a Twin-style simulator, and a City Brain policy simulation. The FastAPI application is the single entry point. The supplied model artifact and its preprocessing code are reused unchanged.

## Start locally on Windows

Extract `Guardian_Unified.zip`, then open PowerShell in the extracted `Guardian_Unified` folder. For the default Downloads location:

```powershell
Set-Location "$env:USERPROFILE\Downloads\Guardian_Unified"
if (!(Test-Path '.venv\Scripts\python.exe')) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r guardian\src\requirements.txt
.\.venv\Scripts\python.exe .\guardian\src\run.py
```

Open <http://127.0.0.1:5000>. The service binds to loopback. Set `$env:PORT = '5001'` before the last command to use a different local port. The dashboard, static React bundle, API, and MCP endpoint all use that same process and port. The included `run.ps1` starts the same service; if your PowerShell policy blocks scripts, use the documented Python command above or run `powershell -ExecutionPolicy Bypass -File .\run.ps1` for this invocation.

The ZIP includes the built React frontend, so Python is sufficient to run the app. To rebuild the frontend after changing its source, install Node.js and pnpm, then run `pnpm install --frozen-lockfile` and `pnpm run build` from the `guardian\web` folder. The Python requirements include FastAPI and Uvicorn in addition to the pinned model stack.

## Demonstration flow

1. Select a scenario in **End-to-end demonstration** and run it. The dashboard marks the generated readings as synthetic.
2. Read each pipeline stage: Layer A, Layer B, Layer C, Random Forest, Guardian verdict, and City Brain response.
3. Use Previous/Next to inspect each reading in multi-reading scenarios. The event timeline records the checks and decisions in processing order.
4. Compare **Suspicious probability** with the separate **Guardian trust score**. The model output is advisory and contributes zero numeric weight to the existing trust scorer.
5. Use **Reading inspector** for the original five RF presets and editable ten-feature input. This is a direct model inspection tool, not a Guardian verdict.
6. Reset the dashboard before a clean jury demonstration.

## Unified architecture and data flow

`src/unified_api.py` serves the existing Guardian FastAPI responsibilities and mounts the original model MCP server and React assets as a fallback. `src/integration_service.py` imports the actual modules from the bundled `guardian_layer/guardian` package: `SensorBuffer`, Layer A HMAC and replay checks, Layer B validation, Layer C correlation, Layer E reputation, and `compute_trust_score`. It calls `src/ml_service.py` directly; internal inference makes no network request. `mocks/simulation.py` generates synthetic sensor inputs and sends them through the same service function used by `POST /ingest`.

For accepted readings, the flow is:

`Twin/simulator → typed ingestion → replay/signature gate → physical/rate/drift and stuck checks → cross-sensor correlation → saved RF inference → existing Guardian trust scorer + reputation → simulated City Brain gate → evaluation record and timeline`

Replay or required-signature failure stops the reading before it enters the buffer, model, or trust scorer. The response records the rejection and shows model inference as skipped. Model unavailability or missing feature history produces no probability. Nothing substitutes a fallback probability.

The existing `compute_trust_score` values, thresholds, verdicts, and reputation update rules remain intact. Its numeric score is not replaced or adjusted by ML. The evaluation record carries the advisory beside the deterministic score and reports `ml_numeric_contribution: 0.0`; no unverified ML weight was introduced. City Brain actions are local simulations only. It blocks Layer A failures, hard bounds/rate failures, stuck sensors, and non-trusted Guardian verdicts. A statistical drift penalty continues to affect the real score; if the existing scorer still returns `trusted`, the City Brain follows that final verdict.

## Sensor and model feature mapping

The adapter supports the model's existing domains and exact ten raw fields from `models/guardian_rf_features.py`. History-derived values follow `models/generate_dataset_v2.py`: six-tick z-score, absolute change per tick, configured bounds, median of up to thirty prior readings, flat-run length, cross-sensor strength, claim flag, and decayed reputation count. The Guardian rate check separately remains change per elapsed second, as implemented by Layer B.

- `traffic_cam → traffic`, `water_level → water`, `power_load → power`, `air_quality → air_quality`, and `emergency_call → emergency`.
- Water arrives in `cm` or `m`; the layer stores meters for its existing physical limits, while RF features use the model's configured centimeters.
- `air_quality` in `AQI` can still pass through Guardian checks, but RF inference is unavailable because AQI cannot be converted losslessly into the model's PM2.5 `ug/m3` quantity. Use `ug/m3` when the reading truly contains PM2.5.
- An RF result is unavailable until a prior reading exists for history-dependent fields. This is reported explicitly.

The model was trained on synthetic data. Its probabilities and published metrics are not real-world security performance claims. Gradual and corroborated attacks can remain undetected. Replay protection is deterministic and is not delegated to ML.

## Scenarios

The simulator includes Normal operation, Genuine fire emergency, Fake fire alert, Replay attack, Invalid signature, Physical anomaly, Stuck sensor, Adaptive ramp, Model unavailable, Corroborated spoofing, and a Custom sensor reading. It uses the actual Layer implementation and saved RF model whenever inference is available. The unavailable scenario explicitly injects an inference outage for its focus reading; it does not synthesize a score or probability. Corroborated spoofing intentionally illustrates a limitation: the existing correlation rules may accept evidence that an adaptive attacker can forge.

## Local API

| Route | Purpose |
|---|---|
| `GET /health` | Guardian readiness and actual model availability/error |
| `POST /ingest` | Unified typed ingestion; returns the existing `reading_id` and `verdict` fields plus the evaluation record |
| `GET /trust_verdict/{sensor_id}/{reading_id}` | Retrieve an accepted Guardian verdict |
| `POST /report_incident` | Record an incident flag for a device |
| `POST /quarantine_device/{device_id}` / `POST /isolate_sensor/{sensor_id}` | Simulated containment controls |
| `POST /rollback_reading` / `GET /reputation/{sensor_id}` | Existing rollback and reputation inspection behavior |
| `GET /api/overview`, `/api/timeline`, `/api/scenarios` | Dashboard health, counters, reputation, event trace, and scenario catalog |
| `POST /api/simulations/{scenario_id}` / `POST /api/reset` | Run a synthetic scenario or reset in-memory demo state |
| `GET /api/capabilities`, `POST /api/advisory` | Original ten-feature model inspector through the same-origin API |
| `POST /mcp` | Existing MCP tools `describe_capabilities` and `evaluate_reading_advisory` |

Unknown `/api/*` paths return JSON 404 responses. The local model debug route `/debug/predict` remains available through the mounted model app but is not linked from the dashboard. No CORS setup is needed because the UI and API share an origin.

## Guardian integration policy and Twin adapters

G5–G8 Guardian-side components are under `src/`: configured Twin SSE/MCP adapters, explicit Twin-event ingestion, action authorization, Ed25519 token issue/verify, structured JSONL logs, score/risk settings, action aliases, and capacity tracking. The detailed request/token contract and external verification limits are in [INTERFACE.md](INTERFACE.md). Copy `guardian/.env.example` values into your shell/deployment secret manager and replace all placeholders. `guardian/.env.example` itself is not auto-loaded.

To consume a configured live Twin feed, start Guardian in one terminal, then run this in another:

```powershell
 $env:TWIN_BASE_URL = 'https://your-twin-host'
 $env:GUARDIAN_TWIN_BEARER_KEY = 'your-guardian-specific-twin-key'
 $env:GUARDIAN_API_BEARER_KEY = 'a-separate-guardian-api-key'
 .\.venv\Scripts\python.exe .\guardian\src\twin_runner.py
```

The feed bridge only processes documented sensor types with an existing Guardian mapping. Partner schemas, real service credentials, Twin simulated-clock adapter, and cross-layer Ed25519 verification must be supplied/verified by the partner teams before claiming a live end-to-end pass. `src/guardian_policy.json` marks risk floors and action-to-risk assignments as provisional where the meeting record did not establish final values. The Power action cap is per run; Telecom/Waste rollback pools reserve three unique node IDs each. These Guardian-side counters do not claim that Twin executed the action.

## Twin and Brain integration runbook

This section separates the integrations that work locally from partner connections that still need a confirmed contract. Guardian's model MCP endpoint (`/mcp`) serves model advisory tools; it is not the Twin MCP endpoint. `src/twin_runner.py` is the Twin client: it reads Twin SSE events at `<TWIN_BASE_URL>/events`, can make Twin MCP calls at `<TWIN_BASE_URL>/mcp`, and posts Twin readings into Guardian's HTTP API. The incoming Twin event route is not itself an MCP server.

### Configure Guardian for a Twin connection

Use two PowerShell terminals from the project root. Replace every example value with credentials and URLs issued for your environment. Do not commit credentials or the private signing key. `.env.example` documents the variable names but is not loaded automatically.

First create a persistent Ed25519 key pair. Keep the private key on the Guardian host and provide only the public key to a partner after agreeing on the exchange channel:

```powershell
New-Item -ItemType Directory -Force secrets | Out-Null
.\.venv\Scripts\python.exe .\guardian\src\generate_token_keys.py `
  --private .\secrets\guardian-ed25519-private.pem `
  --public .\secrets\guardian-ed25519-public.pem
```

In **Terminal 1**, set the Guardian API key and token key paths, then start the service. The API key here protects calls into Guardian; it is separate from the Twin credential:

```powershell
$env:GUARDIAN_API_BEARER_KEY = 'replace-with-a-long-random-guardian-api-key'
$env:GUARDIAN_TOKEN_PRIVATE_KEY = (Join-Path (Get-Location) 'secrets\guardian-ed25519-private.pem')
$env:GUARDIAN_TOKEN_PUBLIC_KEY = (Join-Path (Get-Location) 'secrets\guardian-ed25519-public.pem')
.\.venv\Scripts\python.exe .\guardian\src\run.py
```

In **Terminal 2**, configure the Twin's base URL and its Guardian-specific bearer credential, point the bridge at the local Guardian API, and start the SSE consumer:

```powershell
$env:TWIN_BASE_URL = 'https://your-twin-host'
$env:GUARDIAN_TWIN_BEARER_KEY = 'credential-issued-for-guardian-by-twin'
$env:GUARDIAN_API_BEARER_KEY = 'same-guardian-api-key-as-terminal-1'
$env:GUARDIAN_LOCAL_URL = 'http://127.0.0.1:5000'
.\.venv\Scripts\python.exe .\guardian\src\twin_runner.py
```

The runner subscribes to Twin's `/events`, ignores `hello` and `heartbeat`, and submits each `readings` SSE envelope to `POST /api/integrations/twin/event` with `Authorization: Bearer <GUARDIAN_API_BEARER_KEY>`. It prints the run ID and processed count. The HTTP endpoint returns each evaluation, including the Guardian verdict. Optional Brain delivery is configured separately below.

To check Twin MCP connectivity independently, stop the SSE runner with `Ctrl+C` and use a tool name that the Twin team confirms is available:

```powershell
.\.venv\Scripts\python.exe .\guardian\src\twin_runner.py --tool get_clock --arguments '{}'
```

`get_clock` is an example from the partner notes, not a guarantee that every Twin deployment exposes that tool. The runner initializes an MCP Streamable HTTP client against `<TWIN_BASE_URL>/mcp` and prints the tool result. Do not run the MCP one-off command and SSE listener expecting them to share a single process; use separate invocations/terminals as needed.

### Reading payload and returned verdict

Twin must send a `readings` event with a `run_id` and a `readings` array. The supported sensor names and units are listed in [INTERFACE.md](INTERFACE.md). For example, Twin's SSE data can look like this:

```json
{
  "run_id": "run-42",
  "readings": [{
    "run_id": "run-42",
    "reading_id": "read-17",
    "device_id": "PWR-01-load",
    "node_id": "PWR-01",
    "timestamp": "2026-10-22T12:00:00Z",
    "tick": 17,
    "sensor": "load_kw",
    "channel": null,
    "value": 450,
    "unit": "kW",
    "lat": 36.5,
    "lon": 11.5
  }]
}
```

For a direct local HTTP check, post the same object under `{"event":"readings","data":...}` to `http://127.0.0.1:5000/api/integrations/twin/event` with the Guardian API bearer key. On success the response has `processed`, `skipped`, and `results`; each result contains `reading_id` and `evaluation`. The evaluation includes:

- `guardian.verdict`, `guardian.trust_score`, and `guardian.reasons` — the deterministic Guardian verdict.
- `ml` — a separate RF advisory. It has zero contribution to `trust_score`.
- `city_brain` — the local policy simulation's `allowed`, `blocked`, and reason fields.
- Layer A/B/C details, reputation changes, and the Twin reading identity.

An invalid or absent API key is rejected; an unknown sensor, invalid unit, null reading, or envelope mismatch is reported as skipped rather than scored. Supported Twin mappings are `congestion_index`, `water_level`, `load_kw`, `pm25`, and `emergency_calls`. This adapter does not map Telecom/Waste sensor semantics.

### Delivering a verdict to an external Brain service

“City Brain” in the dashboard and in `evaluation.city_brain` remains a local simulation. The Twin runner now has an optional outbound Brain HTTP webhook for scored Guardian verdicts. To enable it, set `BRAIN_VERDICT_URL` and `GUARDIAN_BRAIN_BEARER_KEY` in the environment used to run `twin_runner.py`; use a separate Brain-issued credential, not either Twin/Guardian credential. The runner sends the versioned `guardian.verdict.v1` payload described in [INTERFACE.md](INTERFACE.md), with a stable `Idempotency-Key` header. It queues each verdict in a durable local JSONL outbox before sending, retries network/408/429/5xx failures, retains failed deliveries, and drains pending entries when restarted. Non-retryable Brain errors fail the runner visibly. Readings rejected before a Guardian verdict exists are not represented as scored verdicts and are not sent to this endpoint.

Before enabling the webhook against a real Brain, the teams need to confirm the endpoint path, bearer credential, accepted payload schema, idempotency behavior, and acknowledgment semantics. Configure the sender after that confirmation:

```powershell
$env:BRAIN_VERDICT_URL = 'https://your-brain-host/api/guardian/verdicts'
$env:GUARDIAN_BRAIN_BEARER_KEY = 'credential-issued-for-guardian-by-brain'
$env:BRAIN_TIMEOUT_SECONDS = '10'
$env:BRAIN_MAX_RETRIES = '3'
$env:BRAIN_RETRY_BASE_SECONDS = '0.5'
$env:GUARDIAN_BRAIN_OUTBOX = 'run-logs/brain-outbox.jsonl'
.\.venv\Scripts\python.exe .\guardian\src\twin_runner.py
```

The webhook sends Guardian's deterministic verdict separately from the RF advisory; ML is not the verdict and has zero trust-score weight. If Brain asks Guardian to authorize an actuator action, call `POST /api/actions/authorize` with the reading ID, action, parameters, risk level, and domain. Guardian returns a short-lived Ed25519 token only when the reading, action policy, risk floor, and signing-key checks pass. The consuming layer must verify the token against the agreed public key, bind it to the exact action and parameters, and enforce one-time use. This repository's local verify endpoint tests that behavior, but cross-service Twin verification has not been validated with a partner.

### Current integration status and implementation report

**Implemented in this repository:**

- Unified FastAPI app, bundled dashboard, saved Random Forest artifact loader, health/capability reporting, model inspector, and synthetic end-to-end simulator.
- Guardian pipeline uses the bundled Guardian layers for replay/signature checks, input/physical/rate/drift checks, correlation, reputation, trust scoring, and a simulated City Brain gate.
- Twin SSE adapter with bearer auth, configured timeouts and bounded retries; Twin Streamable HTTP MCP client for one-off tool calls; Twin-to-Guardian reading normalization and authenticated event ingestion.
- Guardian action allowlist/aliases, risk and trust policy checks, per-run Power action cap, rollback reservation pools, Ed25519 action tokens with 60-second expiry, action/parameter binding, and replay rejection.
- Optional outbound Brain verdict webhook with a Brain-specific bearer credential, versioned payload, stable idempotency key, bounded retries, and a durable JSONL retry outbox.
- JSONL audit records correlated to reading IDs. Token contents, signatures, bearer credentials, and private keys are excluded/redacted.
- Dashboard model availability status correction. A headed Chromium Playwright test for Twin event authentication, reading ingestion, action authorization, token verification, and replay rejection lives in `web/tests/twin-actions.spec.js`.

**Verification recorded:**

- The full browser suite passed: 6 Playwright tests, including saved-model inference and the dashboard pipeline.
- The headed Twin/action-token Playwright test passed against an isolated local server with a temporary API key and Ed25519 key pair: missing-key HTTP 401, event ingestion HTTP 200, authorization HTTP 200, token verification HTTP 200, and replay HTTP 401.
- Brain webhook tests passed for payload shaping, secret separation in headers, HTTP success, transient retry, immediate auth failure, and outbox restart recovery.
- The focused Python local Twin-event/action-token integration test passed. The latest full Python run recorded 44 passed and 2 skipped; the live Twin checks skip until Twin credentials are configured.
- The model artifact loaded successfully locally and `/health` reported `model_available: true`.

**Not verified or not implemented:**

- No live Twin server, credentials, real Twin SSE event stream, Twin MCP tool catalog, simulated-clock adapter, or Twin-side token verification was available for validation.
- No external Brain endpoint, partner payload acceptance, or Brain credential was supplied, so the configurable webhook has not been connected to a real Brain service. The current City Brain result remains simulated locally.
- Policy risk minima and some action mappings remain provisional pending partner confirmation. This project is a demonstration and the model was trained on synthetic data.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q guardian\tests
Push-Location guardian\web
pnpm run build
.\node_modules\.bin\playwright.cmd test --headed
Pop-Location
```

Keep Guardian running in another terminal before the dashboard browser suite; Playwright uses port 5000 by default. Run `.\node_modules\.bin\playwright.cmd install chromium` once if Chromium is missing. If `pnpm` is not on the PowerShell PATH, use the installed local binaries such as `.\node_modules\.bin\vite.cmd build` and `.\node_modules\.bin\playwright.cmd test --headed` from `guardian\web`.

The Twin/action-token browser test needs a Guardian process configured with `GUARDIAN_API_BEARER_KEY` and an Ed25519 signing key. Run it against that configured test instance (not an unconfigured default Guardian process):

```powershell
Push-Location guardian\web
$env:GUARDIAN_PLAYGROUND_URL = 'http://127.0.0.1:5001'
$env:GUARDIAN_API_BEARER_KEY = 'same-local-test-key-used-by-the-test-server'
.\node_modules\.bin\playwright.cmd test tests/twin-actions.spec.js --headed
Pop-Location
```

The test prints the HTTP status and verification summary in Chromium and the Playwright terminal. The Guardian terminal prints route/status access logs. Its token test should use a temporary private/public key pair and an isolated port, following the configuration pattern above. Do not use production keys for automated tests.

## Known limits

- Service state, buffers, verdicts, events, and reputation are in memory and reset when the process restarts.
- The supplied `guardian_layer` code has no standalone test suite; the integration tests exercise its real modules through the unified API.
- The existing cross-sensor rules are illustrative and can count a spoofed signal when it matches the configured correlation story.
- The deterministic scorer does not assign a numeric penalty to stuck readings. The integration adds an explicit Layer B stuck-health gate and blocks City Brain simulation on that failure without changing the trust score.
- Training-data provenance has a metadata discrepancy: the notebook metadata names scikit-learn 1.9.1, while the artifact compatibility requirement and project pin are 1.7.2. The supplied artifact loads and parity tests pass with the pinned dependency.
