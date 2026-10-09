# Twin: Interface Card (draft v6, 7 Oct 2026, must be cut to one page by 10 Oct)

**Status:** the tools in the table exist. Everything else is listed under "Planned" at the bottom. `get_capabilities` lists only the tools the caller can really call.

## Connect
MCP over HTTP (Streamable HTTP), protocol version `2026-07-28`, endpoint `http://<twin-host>:8000/mcp`. The Twin address is a
setting in YOUR config, never hard-coded. Live feed (server-sent events): `GET http://<twin-host>:8000/events` (needs a layer key):
`hello` once, then one `readings` event per tick (all readings of that tick, `id` = `run_id:tick`), `heartbeat` when quiet.
Health: `GET /health` (no key).

## Authenticate
`Authorization: Bearer <your key>` on every request. One key per caller: `city_brain`, `guardian`, and a separate `scenario` key.
The Twin learns who you are from the key. Keys come from the `.env` of whoever runs the Twin. Never commit them.

## Tools
| Tool | Who | Input | Output |
|---|---|---|---|
| `get_capabilities` | anyone | none | versions, who you are logged in as, tools you can call |
| `list_nodes` | `city_brain`, `guardian` | optional `domain` | nodes: `node_id`, domains, zone, x, y, sensors (`device_id`, unit, channels), actuators, neighbours |
| `get_readings` | `city_brain`, `guardian` | optional `domain`, `node_id`, `sensor` | the latest tick's readings (same shape as one feed event) |
| `get_clock` | `city_brain`, `guardian` | none | `run_id`, `tick`, simulated `time`, `tick_seconds`, `speed`, `running` |
| `list_actions` | `city_brain`, `guardian` | none | each action: inputs with allowed values, `risk` (R1 to R3 or null), `preview_required`, `target_nodes`, `action_cap`; plus `token_mode`, `preview_enforced` |
| `actuate` | `city_brain` | `action`, `targets`, `params`, `token`, `idempotency_key` | `status` committed or rejected, `action_id`, `code`, `message`, `details`, `replayed` |
| `isolate_sensor` | `guardian` | `device_ids`, optional `reason`, optional `caused_by` | `status` applied or rejected, `changed`, `unchanged`, `code`, `details` |
| `quarantine_device` | `guardian` | `device_ids`, optional `reason`, optional `caused_by` | same as `isolate_sensor` |
| `rollback_reading` | `guardian` | `reading_ids`, optional `caused_by` | `corrections`: each marked `corrected: true`, with `corrects` (the bad `reading_id`), `restored_from`, `value` |
| `release_device` | `guardian` | `device_ids`, optional `caused_by` | `released`, `not_contained` |
| `get_containment_state` | `city_brain`, `guardian` | none | devices cut off (`isolated` or `quarantined`), corrections, cap use per domain |
| `get_quarantine_lane` | `guardian` | none | readings held off the feed, commands held because of quarantine |
| `run_scenario` | `scenario` key only, hidden from others | `name`, optional `params` | what was started: `scenario_id`, `faults`. Names: `fake_reading`, `stuck_sensor`, `replay_exact`, `list`, `stop`, `reset` |

## actuate: the rules
* `targets` are nodes that carry that actuator (`list_actions` lists them). `params` are the action's inputs, unknown names are refused.
* `token`: Guardian's permission for this exact action, targets and params. Format: three base64url parts `header.payload.signature`
  (a JWT). Payload: `iss` "guardian", `aud` "twin", `jti` (unique, single use), `run_id`, `iat`, `exp` (simulated time), `action`,
  `targets`, `params`, `score`. `token_mode` in `list_actions` says if the signature is required (`signed`, Ed25519 only) or must be empty (`unsigned`).
* `idempotency_key`: same key and same request returns the first answer (`replayed: true`). Same key, changed request: `IDEMPOTENCY_CONFLICT`.
  A refused attempt does not use up the key. Keys are per caller.
* Checks in order: valid request, idempotency, token, preview (not enforced yet), caps. A token is spent only when the action commits.
* Token times (`iat`, `exp`) use the Twin's simulated clock (`get_clock`), which moves 1 s per real second at speed 1.0. Issue tokens from the clock's time, not your wall clock.
* Caps: one request may touch at most `action_cap` nodes per domain. A shared node counts in each domain it belongs to. Over the cap
  refuses the whole request.
* Refusals come back as a normal result with `status: "rejected"` and a `code`: `TOKEN_MISSING`, `TOKEN_INVALID`, `TOKEN_WRONG_RUN`, `TOKEN_EXPIRED`,
  `TOKEN_REUSED`, `TOKEN_MISMATCH`, `TOKEN_SCORE_TOO_LOW`, `IDEMPOTENCY_CONFLICT`, `PREVIEW_REQUIRED`, `CAP_EXCEEDED`, `DEVICE_QUARANTINED`.
* A wrong request is an error instead (the call fails, text `CODE: message`): `UNKNOWN_ACTION`, `UNKNOWN_NODE`, `INVALID_TARGETS`, `INVALID_PARAMS`, `INVALID_IDEMPOTENCY_KEY`.

## Examples (real output, shortened)
A reading, one entry of `readings` (`value` is what the sensor reports, sensors can be wrong, `null` = no value):
```json
{"run_id": "run-42-001", "reading_id": "rd0000007-TRF-01.avg_speed", "tick": 7, "timestamp": "2026-10-05T08:00:07.071Z",
 "node_id": "TRF-01", "device_id": "TRF-01.avg_speed", "sensor": "avg_speed", "channel": null, "value": 35.6, "unit": "km/h"}
```
`actuate` with `{"action": "set_valve_position", "targets": ["WAT-01"], "params": {"position": 40}, "token": "...", "idempotency_key": "demo-1"}`:
```json
{"status": "committed", "run_id": "run-42-001", "tick": 4, "time": "2026-10-05T08:00:04.000Z", "action": "set_valve_position",
 "targets": ["WAT-01"], "params": {"position": 40.0}, "action_id": "ac-00001", "code": null, "replayed": false}
```
Same with three valves (cap for water is 2):
```json
{"status": "rejected", "code": "CAP_EXCEEDED", "message": "This request touches more nodes than ...",
 "details": {"pool": "action", "domain": "water", "cap": 2, "in_use": 0, "requested": 3, "remaining": 2, "violations": ["..."]}}
```

## Errors
No or unknown key: `UNAUTHENTICATED: missing or unknown key. ...`. Known key, not allowed: `FORBIDDEN: '<you>' may not call <tool>.`
Bad input: field name and allowed values. Feed without a key: HTTP 401 `{"error": {"code": "UNAUTHENTICATED", "message": "..."}}`, wrong caller 403.
Messages we send are strict. Messages we receive: unknown extra fields are ignored, missing or wrong required fields are rejected with a message
(exception: unknown names inside `params` are refused, because a silently ignored typo on an actuator command is worse than an error).

## Run log (R2)
The Twin writes `run-logs/<run_id>.twin.jsonl` and merges into `logs/<run_id>.jsonl` (`python -m twin.logmerge <run_id>`). Fields: `run_id`, `event_id`, `timestamp`, `tick`, `wall`, `layer`, `event_type`, `caused_by`, `data`. Twin events: `scenario`, `reading` (faulted readings only), `action` (token ID, not the token), `containment`. No true value is ever in it. Draft, review 9 Oct.
For the timeline arrows (`python -m twin.dashboard`): a verdict's `caused_by` holds the `reading_id` it judged. Guardian's approval event carries `data.token_id` (same as the token), the Brain's decision carries `data.idempotency_key` (same as its `actuate` call). Containment tools take optional `caused_by`: up to 10 event ids, only written to the log.

## Containment: the rules (Guardian only; `release_device`, `get_containment_state`, `get_quarantine_lane` are our additions)
* Device = one sensor at one node (`device_id` from `list_nodes`). `isolate_sensor` removes the device's readings from the feed and `get_readings` from
  the current tick on. `quarantine_device` does the same, and an `actuate` aimed at that node is held (`DEVICE_QUARANTINED`, token not spent).
* `rollback_reading` never uses the true value. It returns the last value the sensor reported that was not already known bad. The feed itself is
  not rewritten: the correction is the tool answer and appears in `get_containment_state`. Errors: `UNKNOWN_READING`, `READING_NOT_PUBLISHED`. Refusal: `NO_TRUSTED_VALUE`.
* Caps count nodes per domain, a device counts in its own sensor's domain. Isolate and quarantine share one pool, rollback has its own.
  A request over a cap is refused whole: `status: "rejected"`, `CAP_EXCEEDED`, with `pool`, `domain`, `cap`, `in_use`, `requested`, `remaining`.
* Repeating isolate or quarantine is harmless. `release_device` frees the slots. Errors for bad input: `UNKNOWN_DEVICE`, `INVALID_DEVICE_IDS`, `INVALID_REASON`.

## Conventions (from CIVIS, 4 Oct)
UTF-8 JSON, snake_case. Stable ids `run_id`, `reading_id`, `device_id` (`<node_id>.<sensor>`), `node_id`. Time: simulated UTC, RFC 3339 with Z plus an integer
`tick` (1 tick = `tick_seconds`, default 1 s, real speed); a reading's `timestamp` may be a few ms off its tick. Missing value: `null`, never zero.
`channel` is set only for sensors split by type (`emergency_calls`: accident, fire, flood, medical; `units_free`: police, ambulance, fire).
Units: congestion 0-100 %, water cm above the sensor's own zero, power kW, PM2.5 ug/m3.

## Planned
* 8 Oct: `congestion_index`, optional
  two-step commit (`status: "pending"`, then `commit_action`, off by default).
* 15-17 Oct: dry-run preview (then `preview_required` is enforced), undo, `get_flagged_readings`, emergency events with transcript.
* Not final: dispatch uses `destination` for the place (CIVIS's table says `target`); `params` as a separate field; token field names.
