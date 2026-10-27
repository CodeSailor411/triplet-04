# CIVIS Brain interface

28 October 2026. Branch `codex/civis-elyes`, following checkpoint `brain-mock-3`. Python 3.12, pinned MCP 2.3.0, protocol `2026-07-28`, Streamable HTTP at `http://127.0.0.1:8001/mcp`. Joint acceptance remains blocked. [Release handover](docs/mock-team/BRAIN_MOCK_3.md), [current contract answers](docs/mock-team/CIVIS_answers_to_9antra_questions_28_Oct_2026.md).

| Brain tool | Input | Output / caller |
|---|---|---|
| `get_capabilities` | `{}` | Public tool inventory; `ready:false` |
| `evaluate_tick` | `{batch}` | `DecisionBatch`; Twin, Guardian, scenario driver |
| `get_active_incidents` | `{run_id}` | Active incidents; authenticated callers |
| `explain_decision` | `{decision_id}` | Saved decision, no execution; authenticated callers |
| `notify_containment` | `{notice}` | Accepted/duplicate acknowledgment; Guardian only |

`notice` fields: `event_id`, `run_id`, `state`, `device_ids`, optional `reading_ids`; states: `isolated`, `quarantined`, `corrected`, `released`.

Guardian notifies after the real Twin effect. ACK means Brain invalidation, not execution. Delivery profile: 3 real seconds per call, one identical retry; deduplication is in memory. No pushed-score webhook is required.

**Input example** (`evaluate_tick`):
```json
{"batch":{"run_id":"r1","tick":1,"time":"2026-10-26T12:00:01Z","tick_seconds":1,"count":1,"readings":[{"run_id":"r1","reading_id":"r1-p1","tick":1,"timestamp":"2026-10-26T12:00:01Z","node_id":"POW-01","device_id":"POW-01.load_kw","sensor":"load_kw","channel":null,"value":60,"unit":"kW"}]}}
```
**Output example** (no incident): `{"run_id":"r1","tick":1,"decisions":[]}`. Decisions carry `decision_id`, `status`, `reason`, original evidence IDs and a refusal code when blocked. Reading IDs, nulls, units and all node domains are preserved; optional `lat`/`lon` are WGS84 degrees.

**Wire workflow:** Twin discovery/readings/containment → detection → Guardian `describe_capabilities` and individual `get_trust_verdict(reading_id,fresh=true)` → typed Gemini plan → validation/required Twin `preview_action` → Guardian `authorize_action` → fresh clock/containment check → Twin `actuate`. Guardian uses `risk_level`, `reading_ids`, `domain`, `idempotency_key`; Brain maps its `decision`, `refusal_code`, `trust_score`. Brain forwards the original signed `g1` token unchanged and never signs or performs containment. Twin keeps `get_capabilities`. [Exact mapping](docs/mock-team/GUARDIAN_CONTRACT.md).

The working branch accepts Guardian's new MCP `{"result":{...}}` scored/pending union and historical flat replies. Pending retries preserve the original ID and bounded window; pending never authorizes.

**Run/config:** from `brain`, `python -m civis_brain --env-file .env.partner`. Copy [partner template](config/partner.env.example), obtain credentials privately, set `PEER_MODE=live`, `LLM_MODE=gemini`, `TWIN_FEED_ENABLED=true`, `GUARDIAN_TRANSPORT=mcp_v3`. Twin defaults to port 8000; Guardian to 5000. Brain and Guardian independently consume real Twin SSE. Use one evaluation driver. Browser presets are isolated fixtures.

**Authentication:** inbound keys `BRAIN_TWIN_CALLER_KEY`, `BRAIN_GUARDIAN_CALLER_KEY`, `BRAIN_SCENARIO_KEY`; outbound `TWIN_BRAIN_KEY` matches Twin's `TWIN_KEY_CITY_BRAIN`, and `GUARDIAN_BRAIN_KEY` matches Guardian's `GUARDIAN_BRAIN_MCP_BEARER_KEY`. All private calls use Bearer auth. Guardian supplies its verification public key to Twin separately.

**Limits:** peer timeout 3 real seconds; verdict-read retries at most 1.5 real seconds; AI at most 60 real seconds. Evidence age is 10 simulated seconds by default, 60 in the explicit mock profile; token validity uses Twin simulated seconds, maximum 60. Gaps, containment, missing verdicts and invalid approvals block. Duplicate commands retain one key/receipt; uncertain retries retain the original request/token. Restart requires reconciliation or a new Twin run.

**Scope:** S01 signal R1, S02 virtual valve R3, S03 Power alert, S04 Air Quality alert, S05 one ambulance R2. Included S02 policy permits only `WAT-01 → WAT-01`, `position:40` percent in Twin mock3 seed42; it does not model hydraulics. S06-S08 live policies remain disabled. GPS proximity supplies context, never safe pipe/grid directions.
