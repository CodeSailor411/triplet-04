# Twin: Interface Card (v7, 10 Oct 2026)

The Twin is the simulated city: it sends sensor readings and receives actuator commands. It calls no other layer.

## Connect and authenticate
* MCP over HTTP, protocol `2026-07-28`: `http://<twin-host>:8000/mcp`. Live feed (SSE): `GET /events`, needs a key: `hello`, then one `readings` event per tick, `heartbeat` when quiet. `GET /health` needs no key.
* `Authorization: Bearer <key>` on every call. One key per caller: `city_brain`, `guardian`, and a hidden `scenario` key. Keys live in the Twin's `.env`, never in the repo.
* Pointing at another partner: the Twin's address is a setting in YOUR config. In `config/twin.yaml`: `server` (host, port), `partners` (Brain and Guardian URLs for the mocks), `dashboard.sources` (log folders). Nothing is hard-coded.

## What it receives (tools)
| Tool | Caller | Input | Returns |
|---|---|---|---|
| `get_capabilities` | any | none | versions, your identity, tools you may call |
| `list_nodes` | Brain, Guardian | `domain`? | nodes: `node_id`, domains, sensors (`device_id`), actuators, neighbours |
| `get_readings`, `get_clock`, `list_actions` | Brain, Guardian | optional filters | latest readings; `run_id`, `tick`, `tick_seconds`; actions with `risk`, `preview_required`, caps |
| `actuate` | Brain | `action`, `targets`, `params`, `token`, `idempotency_key` | `committed` or `rejected`, `code` |
| `isolate_sensor`, `quarantine_device`, `release_device` | Guardian | `device_ids`, `reason`?, `caused_by`? | `applied` or `rejected`, `changed` |
| `rollback_reading` | Guardian | `reading_ids` | corrections: `corrected: true`, `corrects`, `value` (never the true value) |
| `get_containment_state`, `get_quarantine_lane` | Brain, Guardian (lane: Guardian) | none | cut-off devices, corrections, cap use, held commands |
| `run_scenario` | `scenario` key only | `name`, `params`? | started faults. Names: `fake_reading`, `stuck_sensor`, `replay_exact`, `list`, `stop`, `reset` |

## What it sends (one real example each)
Reading, in the feed (`value` is what the sensor reports and can be wrong, `null` = no value):
```json
{"run_id": "run-42-001", "reading_id": "rd0000007-TRF-01.avg_speed", "tick": 7, "timestamp": "2026-10-05T08:00:07.071Z",
 "node_id": "TRF-01", "device_id": "TRF-01.avg_speed", "sensor": "avg_speed", "channel": null, "value": 35.6, "unit": "km/h"}
```
`actuate` call `{"action": "set_valve_position", "targets": ["WAT-01"], "params": {"position": 40}, "token": "...", "idempotency_key": "demo-1"}` returns:
```json
{"status": "committed", "action": "set_valve_position", "targets": ["WAT-01"], "params": {"position": 40.0}, "action_id": "ac-00001", "code": null, "replayed": false}
```
Refusal (three valves, water cap is 2). A refusal is a normal result, not a crash:
```json
{"status": "rejected", "code": "CAP_EXCEEDED", "details": {"pool": "action", "domain": "water", "cap": 2, "in_use": 0, "requested": 3, "remaining": 2}}
```
`isolate_sensor` with `{"device_ids": ["WAT-02.water_level"], "reason": "stuck"}` returns `{"status": "applied", "changed": ["WAT-02.water_level"], "unchanged": []}`.

## Rules
* **Token** (Guardian's permission for this exact action): `header.payload.signature`. Payload: `iss`, `aud`, `jti` (single use), `run_id`, `exp`, `action`, `targets`, `params`, `score`. `list_actions` shows `token_mode`: `signed` (Ed25519) or `unsigned`. Times use the Twin's clock (`get_clock`), 1 tick = 1 s at real speed.
* **Order of checks:** valid request, idempotency, token, preview (not enforced yet), caps. A token is spent only on commit. Same key and request returns the first answer.
* **Refusal codes:** `TOKEN_*`, `IDEMPOTENCY_CONFLICT`, `CAP_EXCEEDED`, `DEVICE_QUARANTINED`. A malformed request fails as `CODE: message`. No key: `UNAUTHENTICATED`, wrong caller: `FORBIDDEN`. Full list in the README.
* **Caps** count nodes per domain. `actuate` counts a shared node in every domain, containment only in the sensor's own domain.
* **Messages:** we send strict JSON, we ignore unknown extra fields, unknown `params` are refused. UTF-8, snake_case, time = simulated UTC (RFC 3339) plus `tick`.
* **Log:** `run-logs/<run_id>.twin.jsonl`, merged into `logs/`. Fields: `run_id`, `event_id`, `timestamp`, `tick`, `wall`, `layer`, `event_type`, `caused_by`, `data`. Timeline links: a verdict's `caused_by` is the `reading_id`, Guardian's approval has `data.token_id`, the Brain's decision has `data.idempotency_key`.

**Not final:** dispatch place is `destination` (CIVIS to confirm). Coming: `lat`/`lon` on readings (12 Oct), two-step commit (15 Oct, off by default), `get_flagged_readings`.
