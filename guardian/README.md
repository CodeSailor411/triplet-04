# TSYP14 Guardian Layer Convergence Mock

One local demonstration app connects the Guardian Layer checks, the supplied Random Forest advisory, a Twin-style simulator, and a City Brain policy simulation. The FastAPI application is the single entry point. The supplied model artifact and its preprocessing code are reused unchanged.

## Start locally on Windows

Clone the repository, open PowerShell at the repository root, and run:

```powershell
Set-Location .\guardian
if (!(Test-Path '.venv\Scripts\python.exe')) { py -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe .\backend\run.py
```

Open <http://127.0.0.1:5000>. The service binds to loopback. Set `$env:PORT = '5001'` before the last command to use a different local port. The dashboard, static React bundle, API, and MCP endpoint all use that same process and port. The included `run.ps1` starts the same service; if your PowerShell policy blocks scripts, use the documented Python command above or run `powershell -ExecutionPolicy Bypass -File .\run.ps1` for this invocation.

The repository includes the built React frontend, so Python is sufficient to run the app. To rebuild the frontend after changing its source, install Node.js and pnpm, then run `pnpm install --frozen-lockfile` and `pnpm run build` from the `web` folder. The Python requirements pin the shared runtime packages and the model stack to exact versions.

## Demonstration flow

1. Select a scenario in **End-to-end demonstration** and run it. The dashboard marks the generated readings as synthetic.
2. Read each pipeline stage: Layer A, Layer B, Layer C, Random Forest, Guardian verdict, and City Brain response.
3. Use Previous/Next to inspect each reading in multi-reading scenarios. The event timeline records the checks and decisions in processing order.
4. Compare **Suspicious probability** with the separate **Guardian trust score**. The model output is advisory and contributes zero numeric weight to the existing trust scorer.
5. Use **Reading inspector** for the original five RF presets and editable ten-feature input. This is a direct model inspection tool, not a Guardian verdict.
6. Reset the dashboard before a clean jury demonstration.

## Unified architecture and data flow

`backend/unified_api.py` serves the existing Guardian FastAPI responsibilities and mounts the original model MCP server and React assets as a fallback. `backend/integration_service.py` imports the actual modules from the bundled `guardian_layer/guardian` package: `SensorBuffer`, Layer A HMAC and replay checks, Layer B validation, Layer C correlation, Layer E reputation, and `compute_trust_score`. It calls `backend/ml_service.py` directly; internal inference makes no network request. `backend/simulation.py` generates synthetic sensor inputs and sends them through the same service function used by `POST /ingest`.

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

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
Push-Location web
pnpm run build
pnpm run test:e2e
Pop-Location
```

Keep `run.ps1` running in another terminal before `pnpm run test:e2e`; Playwright uses the local service at port 5000. The suite needs the pinned Chromium browser. Install it once with `pnpm exec playwright install chromium` if it is missing.

## Known limits

- Service state, buffers, verdicts, events, and reputation are in memory and reset when the process restarts.
- The supplied `guardian_layer` code has no standalone test suite; the integration tests exercise its real modules through the unified API.
- The existing cross-sensor rules are illustrative and can count a spoofed signal when it matches the configured correlation story.
- The deterministic scorer does not assign a numeric penalty to stuck readings. The integration adds an explicit Layer B stuck-health gate and blocks City Brain simulation on that failure without changing the trust score.
- Training-data provenance has a metadata discrepancy: the notebook metadata names scikit-learn 1.9.1, while the artifact compatibility requirement and project pin are 1.7.2. The supplied artifact loads and parity tests pass with the pinned dependency.
