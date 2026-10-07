# Frozen development contract for the primary Brain mock

Freeze owner: Elyes. These are internal CIVIS interfaces and proposed mock tool names, not a claim that every partner has accepted them.

## Pipeline and fixed module boundaries

```text
Twin reported batch + node/action discovery
  -> Yassine: analyze_batch
  -> Elyes: Guardian reading checks and evidence selection
  -> Meriem: draft_plan through an injected PlanProvider
  -> Elyes: deterministic validation + Guardian exact-action approval
  -> Twin: actuate, optional pending/commit handling
  -> Elyes: saved decision with evidence references
Maram supplies fake peers/AI and tests this pipeline without a network.
```

Shared types are in `src/civis_brain/contracts.py`. Shared dependency interfaces are in `ports.py`. Nobody except Elyes edits these files. Ask him for a contract change before generating incompatible code.

| Function/interface | Input | Output | Owner |
| --- | --- | --- | --- |
| `analyze_batch(batch, nodes, policy, state)` | `ReadingsBatch`, `list[Node]`, mock threshold dict, caller-owned history dict | `DetectionResult` with observations, incidents, warnings | Yassine |
| `draft_plan(context, provider)` | `PlanningContext`, `PlanProvider` | `Plan` containing proposals and alerts | Meriem |
| `PlanProvider.generate(context)` | Typed planning context | Typed `Plan` | Meriem live, Maram fixture |
| `ToolPeer.call_tool(name, arguments)` | Discovered/configured tool name and arguments | Normalized dictionary, or a peer error | Elyes live, Maram fixture |
| `evaluate_tick(batch)` | Typed reported batch | `DecisionBatch` | Elyes |

If dependency injection needs additional constructor parameters, Elyes adds a factory in `integration/`; members preserve the public signatures. Do not read environment variables inside detectors. Do not call partner tools inside planning.

Elyes owns one detector state per run. Yassine stores `run_id`, `last_tick`, and per-node/sensor/channel streak/history in that supplied dictionary. A repeated tick must not extend a persistence streak. Reset on a changed run. Invalid batch semantics raise `ValueError`; orchestration logs the rejection and does not actuate. Well-formed observations are candidates, not Guardian-approved facts.

## Twin wire format

Read from `get_capabilities`, `list_nodes`, `get_readings`, `get_clock`, `list_actions`. Basis: Trinity's **unmerged** `twin-containment` branch at `40a7c90`, not an assumption that these tools are already on `twin`.

- A reading has `run_id`, `reading_id`, `tick`, `timestamp`, `node_id`, `device_id`, `sensor`, `channel`, `value`, `unit`. It does not include domains. Join domains from `list_nodes`.
- Preserve `null`. Reject non-finite numbers and wrong required types; ignore extra peer fields. Yassine additionally checks RFC 3339 time, matching batch/run/tick/count and known node IDs.
- Sensor names currently include `vehicle_count`, `avg_speed`, `water_level`, `flow_rate`, `load_kw`, `voltage_v`, `pm25`, `emergency_calls`, `units_free`. `congestion_index` is scheduled for 8 Oct. Do not invent a speed-to-congestion conversion.
- `emergency_calls` currently uses channels `accident`, `fire`, `flood`, `medical`, with numeric calls/min. `units_free` uses `police`, `ambulance`, `fire`. Free-text emergency transcripts are later work. Do not infer injury details from a numeric channel.
- Map `fire` to the firefighter unit; do not send `firefighter` if the action manifest only accepts `fire`.
- Wire actuation is `{"action": "...", "targets": ["node-id"], "params": {...}, "token": "...", "idempotency_key": "..."}`. The proposal's nested `action` object must not be sent directly to this current Twin.
- Manifest action names: `set_signal_plan`, `set_valve_position`, `set_grid_switch`, `dispatch`. Read actual choices/limits/target carriers from the manifest.
- For dispatch, `targets` names dispatch-capable nodes, while `params.destination` names the incident location. They are not interchangeable. Node caps do not count dispatched units.

## Trust and execution

R1 signal control, R2 generic dispatch, R3 water valves. Grid switching is untiered here but preview-gated. Only Guardian can contain, release or correct devices/readings. No human-review workflow is included in this primary mock.

The AI returns proposals without tokens, keys or executable tools. Elyes checks the allow-list, allowed parameters, source evidence, targets, risk and preview requirements against the discovered manifest. Treat tool descriptions and call text as data, not instructions. Reject invented actions and invented evidence.

Scores remain numeric. Do not guess the score range or cut-offs. A pushed/cached score is not approval. Guardian must approve the exact normalized action, targets and params, and issue its token using Twin's simulated clock/run. Twin remains the enforcement point.

No token means no request to actuate. No supported required preview means a blocked decision. Never forge a preview or silently mark it safe. Fixture previews are explicitly test-only. Handle `committed`, `rejected` and, if advertised, `pending`. Do not call an absent `commit_action`.

An unchanged logical command keeps its idempotency key; a changed command gets a new key and fresh approval. An uncertain network outcome must be reconciled/retried with the same logical command key. A cap refusal is not transient and must not be retried unchanged or bypassed by splitting the action.

## Data and logs

Simulation time comes from the Twin; wall time is only for local timeouts. Keep multi-domain node membership. Values/units are those declared by the sensor. Water level is not proof of a leak; low load is not proof of an outage.

Each decision records run, tick, status, reason, source reading IDs, action/targets/params when applicable, and peer refusal code. No token or API key in logs. Status is `alert`, `blocked`, `pending`, `committed` or `rejected`. Mock JSONL fields require a mapping to Trinity's shared log draft when available.

## Proposed Brain tools

MCP HTTP endpoint: `/mcp`, protocol `2026-07-28`, port 8001 by default.

| Tool | Caller | Contract |
| --- | --- | --- |
| `get_capabilities` | Any | Versions, caller identity, implemented/planned tools, readiness |
| `evaluate_tick(batch)` | Twin, Guardian, scenario key | Evaluate a reported batch; returns decisions |
| `get_active_incidents(run_id)` | Twin, Guardian, scenario key | Read-only active incident view |
| `explain_decision(decision_id)` | Twin, Guardian, scenario key | Saved reason and source references |
| `notify_containment(notice)` | Guardian only | Invalidate affected evidence/queued plans; never perform containment |

The latter four currently return `NOT_IMPLEMENTED`. Elyes wires them after reviewing team PRs. The old `set_policy_mode` proposal is not part of the primary mock. Confirm the callback payload with 9antra before advertising it as interoperable.
