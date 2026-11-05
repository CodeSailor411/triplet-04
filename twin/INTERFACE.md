# Twin: Interface Card (v12, 4 Nov 2026)

The Twin is the simulated city: it sends sensor readings and receives actuator commands. It calls no other layer. **Tested version: tag `twin-v1.0`.**

## Connect and authenticate
* MCP over HTTP, protocol `2026-07-28`: `http://<twin-host>:8000/mcp`. Live feed (SSE, needs a key): `GET /events`, with `hello`, one `readings` event per tick, `heartbeat` when quiet. `GET /health` needs no key.
* `Authorization: Bearer <key>` on every call, one key per caller: `city_brain`, `guardian`, and a hidden `scenario` key. Keys live in the Twin's `.env`, never in the repo: `TWIN_KEY_CITY_BRAIN`, `TWIN_KEY_GUARDIAN`, `TWIN_KEY_SCENARIO`.
* Pointing at another partner: addresses are settings in your own config. Ours, `config/twin.yaml`: `server` (host, port), `partners` (URLs), `dashboard.sources` (log folders). Nothing is hard-coded.

## What it receives (tools)
| Tool | Caller | Input | Returns |
|---|---|---|---|
| `get_capabilities` | any | none | versions, who you are, tools you may call, `features` |
| `list_nodes`, `get_city_graph`, `get_nearest_nodes` | Brain, Guardian | `domain`?, `node_id` | nodes (GPS, sensors, actuators, neighbours); the city graph (38 nodes, links); nearest nodes |
| `get_readings`, `get_clock`, `list_actions` | Brain, Guardian | optional filters | latest readings; `run_id`, `tick`; actions with `risk`, `action_cap`, `isolation_caps` |
| `preview_action` | Brain | `action`, `targets`, `params` | dry-run: old and new value, `would_pass_checks`. Changes nothing, no token |
| `actuate` | Brain | `action`, `targets`, `params`, `token`, `idempotency_key` | `committed` or `rejected`, `code` |
| `isolate_sensor`, `quarantine_device`, `release_device` | Guardian | `device_ids`, `reason`? | `applied` or `rejected`, `changed` |
| `rollback_reading` | Guardian | `reading_ids` | corrections (`corrected: true`, never the true value) |
| `get_containment_state`, `get_quarantine_lane` | Brain, Guardian | none | cut-off devices, cap use, held commands |
| `run_scenario` | `scenario` key | `name`, `params`? | names: `fake_reading`, `stuck_sensor`, `replay_exact`, `real_jam`, `list`, `stop`, `reset` |

## Units (as sent in each reading)
`vehicle_count` cars/min, `avg_speed` km/h, `congestion_index` percent (0 to 100), `water_level` cm, `flow_rate` L/s, `load_kw` kW, `voltage_v` V, `pm25` ug/m3, `co_ppm` ppm, `temperature_c` C, `emergency_calls` calls/min, `units_free` units.

## What it sends (one real example each)
Reading in the feed (`value` is what the sensor reports and can be wrong, `null` = no value; `lat`/`lon` = node GPS, an invented city):
```json
{"run_id": "run-42-001", "reading_id": "rd0000007-TRF-01.avg_speed", "tick": 7, "timestamp": "2026-10-05T08:00:07.071Z",
 "node_id": "TRF-01", "device_id": "TRF-01.avg_speed", "sensor": "avg_speed", "channel": null, "value": 35.6, "unit": "km/h",
 "lat": 35.98748, "lon": 9.96593}
```
`actuate` with `{"action": "set_valve_position", "targets": ["WAT-01"], "params": {"position": 40}, "token": "...", "idempotency_key": "demo-1"}` returns:
```json
{"status": "committed", "action": "set_valve_position", "targets": ["WAT-01"], "params": {"position": 40.0}, "action_id": "ac-00001", "code": null, "replayed": false}
```
A refusal is a normal result, not a crash (three valves, water cap is 2):
```json
{"status": "rejected", "code": "CAP_EXCEEDED", "details": {"pool": "action", "domain": "water", "cap": 2, "in_use": 0, "requested": 3, "remaining": 2}}
```
`isolate_sensor` with `{"device_ids": ["WAT-02.water_level"]}` returns `{"status": "applied", "changed": ["WAT-02.water_level"]}`.

**Rules** (token, check order, refusal codes, caps, log, what is built): `README.md`, section "Rules and status".
