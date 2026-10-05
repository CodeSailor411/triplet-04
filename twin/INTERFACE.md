# Twin: Interface Card (draft v2, 5 Oct 2026, one page)

**Status:** skeleton. Only the tools marked "now" exist. Everything else is planned and listed at the bottom.

## Connect
MCP over HTTP (Streamable HTTP), protocol version `2026-07-28`, endpoint `http://<twin-host>:8000/mcp`.
The Twin address is a setting in YOUR config (`partners.twin.url` style), never hard-coded.
Live feed (server-sent events): `GET http://<twin-host>:8000/events`. Health: `GET /health` (no key).

## Authenticate
Send `Authorization: Bearer <your key>` on every request. One key per caller: `city_brain`, `guardian`, and a
separate `scenario` key for running scenarios. The Twin finds out who you are from the key, so a layer cannot
pretend to be another. Keys come from the `.env` file of whoever runs the Twin. Never commit them.

## Tools (now)
| Tool | Who | Input | Output |
|---|---|---|---|
| `get_capabilities` | anyone, no key needed | none | layer, versions, protocol version, who you are logged in as, tools you can call |
| `list_nodes` | `city_brain`, `guardian` | optional `domain`: traffic, water, power, air_quality, emergency | seed, count, nodes (`node_id`, domains, role, zone, x, y, sensors with units, actuators, neighbours) |
| `run_scenario` | `scenario` key only. Not in anyone else's tool list | `name` | not implemented yet |

## Example: ask who you are (real output)
Call `get_capabilities` with the City Brain key:
```json
{"layer": "twin", "layer_version": "0.1.0", "mcp_sdk_version": "2.3.0", "protocol_version": "2026-07-28",
 "authenticated_as": "city_brain", "tools_you_can_call": ["get_capabilities", "list_nodes"]}
```
With no key, `authenticated_as` is `null`: use this to check your key before anything else.

## Example: nodes (real output, shortened)
Call `list_nodes` with `{"domain": "emergency"}`:
```json
{"seed": 42, "count": 7, "nodes": [{"node_id": "EMG-01", "label": "old_town", "domains": ["emergency"],
  "role": "call_place", "zone": "old_town", "x": 1034.3, "y": 652.8,
  "sensors": [{"name": "emergency_calls", "unit": "calls/min"}], "actuators": [],
  "neighbours": ["EMG-05", "EMG-03", "AIR-05", "TRF-05"]}]}
```

## Errors (clear text, same shape every time)
* No or unknown key: `UNAUTHENTICATED: missing or unknown key. Send 'Authorization: Bearer <your key>'.`
* Known key, not allowed: `FORBIDDEN: '<you>' may not call <tool>.`
* Bad input: the field name and the allowed values, for example `domain: Input should be 'traffic', 'water', ...`
* Feed without a key: HTTP 401 with `{"error": {"code": "UNAUTHENTICATED", "message": "..."}}`; wrong caller: 403.
* Messages we send are strict. Messages we receive: unknown extra fields are ignored, missing or wrong required fields are rejected with a message.

## Conventions we follow (from CIVIS, 4 Oct)
UTF-8 JSON, snake_case. Ids: `run_id`, `reading_id`, `device_id`, `node_id` (stable). `domains` can hold several.
Time (from 6 Oct): simulated UTC, RFC 3339 with Z (`2026-10-04T08:00:00.000Z`) plus an integer `tick`; the tick length is declared per run.
A missing value is JSON `null`, never zero. A corrected reading keeps a reference to the original.
Units: traffic congestion index 0-100 %, water level in cm above that sensor's own zero, power load kW, PM2.5 ug/m3.

## Planned, in this order
* 6 Oct: readings on `/events` and read tools, simulated clock, `congestion_index`.
* 7 Oct: `actuate(action, targets, token, idempotency_key)`, `list_actions` (with `risk` and `preview_required` per action),
  caps. A cap breach rejects the whole request: `CAP_EXCEEDED` with `domain`, `cap`, `in_use`, `requested`, `remaining`.
  Same idempotency key with a changed request is rejected. A token is single-use and expires.
* 8 Oct: `isolate_sensor`, `quarantine_device`, `rollback_reading`, `release_device` (Guardian only), scenario engine
  (fake reading, stuck sensor, replayed reading).
* 15-17 Oct: `commit_action`, dry-run preview, undo, `get_flagged_readings`, emergency events with transcript.
