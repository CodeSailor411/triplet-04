# CIVIS Brain interface

Updated 6 November 2026. Branch `codex/civis-elyes`, following checkpoint `brain-mock-3`. Python 3.12, pinned MCP 2.3.0, protocol `2026-07-28`, Streamable HTTP at `http://127.0.0.1:8001/mcp`; `GET /health` is also available. The latest recorded gate used Twin `twin-mock-3` (`b012c94`) and Guardian `guardian_final_version` (`f23e570`): 22 checks passed and 8 failed. Joint acceptance is not complete. See [release handover](docs/mock-team/BRAIN_MOCK_3.md) and [Guardian contract](docs/mock-team/GUARDIAN_CONTRACT.md).

| Brain tool | Input | Output | Allowed caller |
|---|---|---|---|
| `get_capabilities` | `{}` | Layer/version, `ready:false`, authenticated identity, implemented tools | Any caller; no key required |
| `evaluate_tick` | `{batch}` | `DecisionBatch` | Twin, Guardian, scenario driver |
| `get_active_incidents` | `{run_id}` | `{run_id, incidents}` | Twin, Guardian, scenario driver |
| `explain_decision` | `{decision_id}` | `{found, decision}`; read only | Twin, Guardian, scenario driver |
| `notify_containment` | `{notice}` | Acknowledgment below | Guardian only |

Private calls use `Authorization: Bearer <key>`. Inbound keys are `BRAIN_TWIN_CALLER_KEY`, `BRAIN_GUARDIAN_CALLER_KEY` and `BRAIN_SCENARIO_KEY`; all must be distinct and nonempty. Unknown or absent keys receive `UNAUTHENTICATED`; a valid key without permission receives `FORBIDDEN`. Outbound `TWIN_BRAIN_KEY` matches Twin's `TWIN_KEY_CITY_BRAIN`; `GUARDIAN_BRAIN_KEY` matches Guardian's `GUARDIAN_BRAIN_MCP_BEARER_KEY`. Guardian separately supplies its public verification key to Twin.

## `notify_containment`

Guardian should call this after Twin confirms a containment effect. The acknowledgment confirms Brain invalidated evidence; it does not report an action or containment operation performed by Brain.

```json
{"notice":{"event_id":"containment-r1-17","run_id":"r1","state":"quarantined","device_ids":["WAT-01.water_level"],"reading_ids":["r1-w17"]}}
```

Required fields are `event_id`, `run_id`, `state` and `device_ids`. `reading_ids` is optional and defaults to an empty list. States are `isolated`, `quarantined`, `corrected` or `released`.

* New event: `{"accepted":true,"invalidated":2,"committed_effects_unchanged":true}`; count varies.
* Repeated `event_id`: `{"accepted":true,"duplicate":true}`. Deduplication is in memory.
* Different run: `{"accepted":false,"code":"RUN_MISMATCH"}`.

`isolated` and `quarantined` block the devices. `released` unblocks them but does not restore invalidated evidence. `corrected` invalidates affected evidence but does not release a blocked device; new evidence must use new reading IDs.

The specified delivery profile is 3 real seconds per call and at most one identical retry after a lost acknowledgment. The current joint gate did not verify Guardian's live containment sender or this end-to-end path.

Guardian notifies after the real Twin effect. ACK means Brain invalidation, not execution. Delivery profile: 3 real seconds per call, one identical retry; deduplication is in memory. No pushed-score webhook is required.

**Input example** (`evaluate_tick`):
```json
{"batch":{"run_id":"r1","tick":1,"time":"2026-10-26T12:00:01Z","tick_seconds":1,"count":1,"readings":[{"run_id":"r1","reading_id":"r1-p1","tick":1,"timestamp":"2026-10-26T12:00:01Z","node_id":"POW-01","device_id":"POW-01.load_kw","sensor":"load_kw","channel":null,"value":60,"unit":"kW"}]}}
```
**Output example** (no incident): `{"run_id":"r1","tick":1,"decisions":[]}`. Decisions carry `decision_id`, `status`, `reason`, original evidence IDs and a refusal code when blocked. Reading IDs, nulls, units and all node domains are preserved; optional `lat`/`lon` are WGS84 degrees.

**Wire workflow:** Twin discovery/readings/clock → incident detection and typed plan → Guardian `describe_capabilities` and an individual `get_trust_verdict(reading_id,fresh=true)` for each source reading → command validation and required Twin `preview_action` → Guardian `authorize_action` for the exact intent → fresh clock and containment check → Twin `actuate`. Guardian's authorization request includes `run_id`, `reading_ids`, `action`, `targets`, `params`, `risk_level`, `domain` and `idempotency_key`. Brain maps `decision`, `refusal_code` and `trust_score`, and forwards the original signed `g1` token unchanged. It never signs tokens or performs containment. Twin keeps its own `get_capabilities`. [Exact mapping](docs/mock-team/GUARDIAN_CONTRACT.md).

The working branch accepts Guardian's new MCP `{"result":{...}}` scored/pending union and historical flat replies. Pending retries preserve the original ID and bounded window; pending never authorizes.

**Run/config:** from `brain`, `python -m civis_brain --env-file .env.partner`. Copy [partner template](config/partner.env.example), obtain credentials privately, set `PEER_MODE=live`, `LLM_MODE=gemini`, `TWIN_FEED_ENABLED=true`, `GUARDIAN_TRANSPORT=mcp_v3`. Twin defaults to port 8000; Guardian to 5000. Brain and Guardian independently consume real Twin SSE. Use one evaluation driver. Browser presets are isolated fixtures.

**Authentication:** inbound keys `BRAIN_TWIN_CALLER_KEY`, `BRAIN_GUARDIAN_CALLER_KEY`, `BRAIN_SCENARIO_KEY`; outbound `TWIN_BRAIN_KEY` matches Twin's `TWIN_KEY_CITY_BRAIN`, and `GUARDIAN_BRAIN_KEY` matches Guardian's `GUARDIAN_BRAIN_MCP_BEARER_KEY`. All private calls use Bearer auth. Guardian supplies its verification public key to Twin separately.

**Limits:** peer timeout 3 real seconds; verdict-read retries at most 1.5 real seconds; AI at most 60 real seconds. Evidence age is 10 simulated seconds by default, 60 in the explicit mock profile; token validity uses Twin simulated seconds, maximum 60. Gaps, containment, missing verdicts and invalid approvals block. Duplicate commands retain one key/receipt; uncertain retries retain the original request/token. Restart requires reconciliation or a new Twin run.

**Scope and known limits:** S01 signal R1, S02 virtual valve R3, S03 Power alert, S04 Air Quality alert, S05 one ambulance R2. The S02 mock policy permits only `WAT-01` to `WAT-01`, `position:40` percent in Twin mock 3 seed 42; it is a virtual-command allowlist, not a hydraulic safety model. The live S02 path remains blocked by Guardian's safe-preview refusal. S05 remains blocked because Guardian does not return a current verdict for native ambulance `units_free` evidence. S06-S08 live policies remain disabled. GPS proximity supplies geographic context, not verified road, pipe or grid paths.

**Optional local experiment:** `TRAFFIC_GNN_SHADOW_ENABLED=true` enables the S01 five-tick traffic forecast and separate, read-only Gemini interpretation. It is disabled by default, uses Twin `vehicle_count`/`avg_speed` reports and same-domain geographic neighbour links, and never enters action planning or authorization. Output appears in `/debug/state`; no MCP tool is added. The graph links are not confirmed road links and the experiment has not shown a meaningful improvement over its non-graph baseline. See `experiments/traffic_gnn/README.md` for training details and limits.

The tested Guardian contract comes from `guardian_final_version`, not the older bundled `guardian/` snapshot. Its published MCP tools include `describe_capabilities`, `get_trust_verdict` and `authorize_action`. Tool availability does not mean the full workflow passes. The latest gate did not show Guardian confirming containment in Twin and then notifying Brain; that live path remains blocked.
