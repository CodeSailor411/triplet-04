# Unified Guardian interface

The local React dashboard and the Guardian API run on one loopback origin, by default `http://127.0.0.1:5000`. The service is implemented in `backend/unified_api.py`. API payloads are validated, unknown fields are rejected for ingestion, numeric inputs must be finite, and unknown `/api` routes return JSON 404.

## Sensor ingestion

`POST /ingest` accepts the original Guardian Layer fields plus an optional reading ID:

```json
{
  "sensor_id": "power_load_09",
  "sensor_type": "power_load",
  "value": 500,
  "unit": "kW",
  "timestamp": 1792000000.0,
  "location": {"lat": 37.27, "lng": 9.87},
  "sequence_number": 1,
  "signature": null,
  "incident_type": "fire",
  "require_signature": false,
  "reading_id": null
}
```

Valid `sensor_type` values are `traffic_cam`, `water_level`, `power_load`, `air_quality`, and `emergency_call`. Units are checked by sensor. Water accepts `cm` or `m`; air quality accepts `AQI` or model PM2.5 `ug/m3`; traffic accepts `percent` or `%`; power accepts `kW`; emergency calls accept `calls_per_min` or `calls/min`.

On acceptance the response keeps the original top-level `reading_id` and `verdict`, and adds an `evaluation` object containing original nonsensitive reading fields, Layer A/B/C results, model state/features/probability, Guardian score/reasons/breakdown, reputation change, City Brain simulation, and action-blocked state. The raw signature is never returned or logged. A replay/out-of-order sequence returns HTTP 409; an invalid required signature returns HTTP 401. These responses also contain the recorded evaluation, with inference marked skipped.

`GET /trust_verdict/{sensor_id}/{reading_id}` returns the original Guardian verdict shape for accepted readings. Other original Layer routes remain available: `/report_incident`, `/quarantine_device/{device_id}`, `/isolate_sensor/{sensor_id}`, `/rollback_reading`, and `/reputation/{sensor_id}`.

## Dashboard APIs

- `GET /health` (also `/api/health`) reports Guardian readiness, model availability, model version, and load error.
- `GET /api/overview` returns counters, active simulated incident records, and per-sensor reputation.
- `GET /api/scenarios` returns scenario descriptions and the supported sensor/domain/unit options.
- `GET /api/timeline?limit=100` returns chronological service events; limit is 1–500.
- `GET /api/evaluations?limit=50` returns recent full evaluation records; limit is 1–200.
- `POST /api/simulations/{scenario_id}` runs one complete scenario. The `custom` scenario accepts `{ "sensor_type": "water_level", "value": 62 }`. Other scenario IDs are `normal`, `genuine_fire`, `fake_fire`, `replay`, `invalid_signature`, `physical_anomaly`, `stuck_sensor`, `adaptive_ramp`, `model_unavailable`, and `corroborated_spoof`.
- `POST /api/reset` clears this process's demo buffers, verdicts, reputation, and event history.
- `GET /api/capabilities` and `POST /api/advisory` serve the manual RF inspector. The latter accepts the same ten ordered model fields as the MCP tool and returns only the model advisory, not a Guardian score or action authorization.

## MCP model tools

MCP Streamable HTTP remains mounted at `POST /mcp` with protocol revision `2026-07-28`. It exposes `describe_capabilities` and `evaluate_reading_advisory`; the latter uses the existing `RAW_INPUT_COLUMNS` order and preserves model null handling and preprocessing. The frontend inspector uses same-origin REST to avoid requiring a browser MCP client package; the MCP tools remain available for existing MCP clients and are exercised by the Python parity suite.

## Security and policy

Layer A rejects replay/out-of-order and failed required HMAC signatures before the RF call. Layer B and Layer C evidence, then the real Layer scorer and reputation policy, remain authoritative. The RF suspicious probability is separate from the Guardian trust score and has no numeric score weight. City Brain outputs are simulated only; no action token or real containment operation is issued. HMAC keys and signatures are not included in API responses, events, or logs.
