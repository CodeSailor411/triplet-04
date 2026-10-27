# Twin: Interface Card (v9, 23 Oct 2026)

The Twin is the simulated city: it sends sensor readings and receives actuator commands. It calls no other layer. **Tested version: tag `twin-mock-3`** (branch `twin-mock-3`).

## Connect and authenticate
* MCP over HTTP, protocol `2026-07-28`: `http://<twin-host>:8000/mcp`. Time: 1 tick = 1 simulated second = 1 real second (at speed 1; `get_clock` shows `tick_seconds` and `speed`). Live feed (SSE): `GET /events`, needs a key: `hello`, then one `readings` event per tick, `heartbeat` when quiet. A reader more than 100 ticks behind jumps ahead and the next event carries `skipped_ticks`; a reconnect starts at the current tick (nothing is replayed). `GET /health` needs no key.
* `Authorization: Bearer <key>` on every call. One key per caller: `city_brain`, `guardian`, and a hidden `scenario` key. Keys live in the Twin's `.env`, never in the repo; the variable names are `TWIN_KEY_CITY_BRAIN`, `TWIN_KEY_GUARDIAN`, `TWIN_KEY_SCENARIO`.
* Pointing at another partner: the Twin's address is a setting in YOUR config. In `config/twin.yaml`: `server` (host, port), `partners` (Brain and Guardian URLs for the mocks), `dashboard.sources` (log folders). Nothing is hard-coded.

## What it receives (tools)
| Tool | Caller | Input | Returns |
|---|---|---|---|
| `get_capabilities` | any | none | versions, your identity, tools you may call, `features` (token formats and mode, preview, sensors, what is not built). The decision report calls this call "describe capabilities"; Guardian's is named `describe_capabilities` |
| `list_nodes` | Brain, Guardian | `domain`? | nodes: `node_id`, domains, `lat`/`lon`, sensors (`device_id`), actuators, neighbours |
| `get_readings`, `get_clock`, `list_actions` | Brain, Guardian | optional filters | latest readings; `run_id`, `tick`, `tick_seconds`; actions with `risk`, `preview_required`, `action_cap`; `isolation_caps` per domain |
| `preview_action` | Brain | `action`, `targets`, `params` | dry-run: old and new value per node, `would_pass_checks`, `blocked_by`. Changes nothing, needs no token |
| `actuate` | Brain | `action`, `targets`, `params`, `token`, `idempotency_key` | `committed` or `rejected`, `code` |
| `isolate_sensor`, `quarantine_device`, `release_device` | Guardian | `device_ids`, `reason`?, `caused_by`? | `applied` or `rejected`, `changed` |
| `rollback_reading` | Guardian | `reading_ids` | corrections: `corrected: true`, `corrects`, `value` (never the true value) |
| `get_city_graph` | Brain, Guardian | `include_matrix`?, `include_roads`? | the city graph: 38 nodes (GPS, zone, domains, sensors, actions with risk), 67 links (`distance_m`, `bearing_a_to_b_deg`, `kind`), zones, roads, and `distance_matrix_m` between every pair in `node_order`. Straight-line distances, not along roads or pipes. Fixed for the run |
| `get_nearest_nodes` | Brain, Guardian | `node_id`, `domain`?, `role`?, `limit`? (1 to 50, default 5) | nearest nodes first: `distance_m`, `bearing_deg`, `linked`. Refusals `UNKNOWN_NODE`, `UNKNOWN_ROLE`, `BAD_LIMIT` |
| `get_containment_state`, `get_quarantine_lane` | Brain, Guardian (lane: Guardian) | none | cut-off devices, corrections, cap use, held commands |
| `run_scenario` | `scenario` key only | `name`, `params`? | started faults. Names: `fake_reading`, `stuck_sensor`, `replay_exact`, `list`, `stop`, `reset` |

## Units (as sent in each reading)
`vehicle_count` cars/min, `avg_speed` km/h, `congestion_index` percent (0 to 100, one per traffic node, added 23 Oct), `water_level` cm, `flow_rate` L/s, `load_kw` kW, `voltage_v` V, `pm25` ug/m3, `co_ppm` ppm, `temperature_c` C, `emergency_calls` calls/min, `units_free` units. 120 readings per tick.

## What it sends (one real example each)
Reading, in the feed (`value` is what the sensor reports and can be wrong, `null` = no value):
```json
{"run_id": "run-42-001", "reading_id": "rd0000007-TRF-01.avg_speed", "tick": 7, "timestamp": "2026-10-05T08:00:07.071Z",
 "node_id": "TRF-01", "device_id": "TRF-01.avg_speed", "sensor": "avg_speed", "channel": null, "value": 35.6, "unit": "km/h",
 "lat": 35.98748, "lon": 9.96593}
```
`lat`/`lon`: GPS of the node, WGS84 degrees, 5 decimals, fixed for the whole run. The city is invented, the anchor point is arbitrary (see `list_nodes`/`topology.json` `geo`). Distances are reference only: nothing in the Twin checks them.
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
* **Token** (Guardian's permission for this exact action): Guardian's own format `g1.<payload>.<signature>` (Ed25519, always signed, claims `token_id`, `trust_score`, `idempotency_key`, times in seconds) or our `header.payload.signature` (`jti`, `score`). Both need `iss` guardian, `aud` twin, `run_id`, `exp`, `action`, `targets`, `params`; lifetime 1 to 60 s, score 0 to 1, single use. A `g1` token with an `idempotency_key` only works with that same key. `list_actions` shows `token_mode`. Times use the Twin's clock (`get_clock`), 1 tick = 1 s at real speed.
* **Order of checks:** valid request, idempotency, token, preview, caps. Actions with `preview_required` need a `preview_action` of exactly the same request first (valid 60 ticks, used up by one commit), else `PREVIEW_REQUIRED`. A token is spent only on commit. Same key and request returns the first answer.
* **Refusal codes:** `TOKEN_*`, `IDEMPOTENCY_CONFLICT`, `CAP_EXCEEDED`, `DEVICE_QUARANTINED`, `PREVIEW_REQUIRED`, `STATE_UNAVAILABLE` (the Twin cannot check token use, nothing was done, retry). A malformed request fails as `CODE: message`. No key: `UNAUTHENTICATED`, wrong caller: `FORBIDDEN`. Full list in the README.
* **Caps** count nodes per domain. `actuate` counts a shared node in every domain, containment only in the sensor's own domain.
* **Messages:** we send strict JSON, we ignore unknown extra fields, unknown `params` are refused. UTF-8, snake_case, time = simulated UTC (RFC 3339) plus `tick`.
* **Log:** `run-logs/<run_id>.twin.jsonl`, merged into `logs/`. Fields: `run_id`, `event_id`, `timestamp`, `tick`, `wall`, `layer`, `event_type`, `caused_by`, `data`. Timeline links: a verdict's `caused_by` is the `reading_id`, Guardian's approval has `data.token_id`, the Brain's decision has `data.idempotency_key`.

**Implemented:** everything above, including the city graph agreed with CIVIS on 23 Oct (our extra, not a Phase 1 requirement). **Planned, not built:** two-step commit (`commit_action`), `get_flagged_readings`, Telecom and Waste domains. **Not final:** dispatch place is `destination` (CIVIS to confirm).
