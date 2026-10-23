# Guardian Layer — Starter Implementation (TSYP14 City Brain Convergence)

A working, runnable skeleton for the Guardian layer: ingestion, validation,
correlation-based spoofing detection, reputation tracking, and the
MCP-style tools City Brain and the Twin will call.

## Project structure

```
guardian_layer/
├── guardian/
│   ├── models.py       # SensorReading, ActuatorCommand, TrustVerdict
│   ├── security.py      # HMAC signing/verification (Layer A security)
│   ├── buffer.py         # rolling per-sensor history, replay detection
│   ├── validation.py    # physical bounds, rate-of-change, z-score drift
│   ├── correlation.py   # cross-sensor spoofing detection (Layer C)
│   ├── reputation.py    # per-sensor trust history with time decay
│   ├── scoring.py        # combines all layers into one TrustVerdict
│   └── main.py            # FastAPI service exposing the tools
├── demo.py                # simulates Twin sending normal + spoofed data
└── README.md
```

## Running it

```bash
pip install fastapi uvicorn pydantic requests
uvicorn guardian.main:app --reload --port 8001
```

In another terminal:

```bash
python demo.py
```

You should see:
- Normal baseline readings scored `trusted` (score 1.0)
- A genuine "fire" signal with corroborating air-quality and emergency-call
  evidence scored `trusted`
- A spoofed "fire" signal with no corroborating evidence scored `suspect`,
  flagged `no_correlated_evidence`
- A replayed (already-used) sequence number rejected with HTTP 409
- The sensor's reputation record showing the flag it picked up

## API endpoints (your MCP-style tool contract)

| Endpoint | Purpose |
|---|---|
| `POST /ingest` | Twin pushes a new sensor reading here |
| `GET /trust_verdict/{sensor_id}/{reading_id}` | City Brain calls this **before acting** on a reading |
| `POST /report_incident` | Log an incident for audit / manually flag a device |
| `POST /quarantine_device/{device_id}` | Containment action |
| `POST /isolate_sensor/{sensor_id}` | Containment action |
| `POST /rollback_reading` | Restore the last known-good value for a sensor |
| `GET /reputation/{sensor_id}` | Debug: inspect a sensor's trust history |

## What's already working

- **Layer A (protocol)**: sequence-number replay/out-of-order rejection;
  optional HMAC signature verification (`security.py`) — turn it on by
  setting `require_signature: true` in your ingest payload once your Twin
  team actually signs readings.
- **Layer B (physical plausibility)**: hardcoded bounds + rate-of-change
  limits per sensor type, plus a z-score outlier check against recent
  history.
- **Layer C (correlation)**: a small, tunable table (`EVENT_CORRELATIONS`)
  checking whether an incident's expected corroborating signals actually
  moved in a baseline-aware time window before/after the primary signal.
- **Layer D (command/effect)**: not implemented yet — this needs a live
  feed of City Brain's actual dispatch calls, which you'll need to agree
  on with your teammates (see "Next steps").
- **Layer E (reputation)**: time-decayed flag tracking per sensor, feeding
  back into future trust scores.

## Tuning knobs you'll want to adjust

- `guardian/validation.py`: `BOUNDS` and `MAX_RATE_OF_CHANGE` — replace
  the placeholder ranges with your Twin's actual simulated sensor ranges.
- `guardian/correlation.py`: `EVENT_CORRELATIONS` — this is the table to
  workshop with your City Brain teammate. It currently covers
  fire/flood/accident/traffic_jam; add more incident types as needed.
- `guardian/scoring.py`: the score penalties (`-0.5`, `-0.35`, etc.) and
  the `TRUSTED_THRESHOLD` / `SUSPECT_THRESHOLD` cutoffs — tune these once
  you see real fault-injection behavior in joint testing with your triplet.

## Next steps (in priority order)

1. **Agree the exact JSON schema** for sensor readings and actuator
   commands with your Twin and City Brain teammates. The `IngestRequest`
   model in `main.py` is your current proposal — get it locked in writing
   before anyone builds further on top of it.
2. **Turn on signature verification** once the Twin team can sign
   readings — this is the single highest-value security addition for the
   least code (see `security.py`).
3. **Get visibility into City Brain's actuator dispatch calls** so you can
   implement Layer D (command/effect verification) — e.g. Twin logs every
   actuator command to a shared endpoint Guardian can also poll.
4. **Add a subscribe/webhook endpoint** so City Brain gets pushed trust
   updates instead of only polling — a sensor trusted 10 seconds ago may
   not be trustworthy now.
5. **Load-test latency** — a trust verdict that arrives after City Brain
   already acted is useless. Measure `/trust_verdict` response time under
   realistic request volume before the joint demo.
6. **Write a few of your own fault-injection tests** beyond `demo.py`:
   gradual sensor drift, coordinated multi-sensor spoofing, and a dropped
   actuator command — these map to the adversarial conditions judges are
   likely to test.
