# CIVIS Brain interface

**7 November 2026:** [current source pins and verification](docs/mock-team/JOINT_FIX_2026-11-07.md). The 14-check actual-service gate passes for the reviewed Twin and Guardian sources, including S02/S05 and real containment notification. Planning was recorded; full production readiness and live Gemini are not certified. Public schemas and `ready:false` are unchanged.

Updated 6 November 2026. Branch `codex/civis-elyes`, following checkpoint `brain-mock-3`. Python 3.12, pinned MCP 2.3.0, protocol `2026-07-28`, Streamable HTTP at `http://127.0.0.1:8001/mcp` (`GET /health` also served). Joint acceptance is not complete. [Release handover](docs/mock-team/BRAIN_MOCK_3.md).

## Public tools and caller permissions

| Brain tool | Input | Output | Allowed callers |
| --- | --- | --- | --- |
| `get_capabilities` | `{}` | Layer, version, `ready:false`, `authenticated_as`, implemented tools | Any (no key required) |
| `evaluate_tick` | `{batch}` | `DecisionBatch` | Twin, Guardian, scenario driver |
| `get_active_incidents` | `{run_id}` | `{run_id, incidents}` | Twin, Guardian, scenario driver |
| `explain_decision` | `{decision_id}` | `{found, decision}`; read only, no execution | Twin, Guardian, scenario driver |
| `notify_containment` | `{notice}` | Acknowledgment (below) | **Guardian only** |

Private calls use `Authorization: Bearer <key>`. Inbound keys: `BRAIN_TWIN_CALLER_KEY`, `BRAIN_GUARDIAN_CALLER_KEY`, `BRAIN_SCENARIO_KEY`; Brain refuses to start unless the three are distinct and nonempty. Errors: `UNAUTHENTICATED` (no or unknown key), `FORBIDDEN` (key not allowed for the tool). Outbound keys: `TWIN_BRAIN_KEY` (must match the key Twin registers as `TWIN_KEY_CITY_BRAIN`) and `GUARDIAN_BRAIN_KEY` (must match the bearer key Guardian is configured to accept from Brain). Guardian supplies its verification public key to Twin separately.

## `notify_containment`

Guardian calls it after the real Twin containment effect. An ACK means Brain invalidated its own state; it does not mean Brain executed anything.

```json
{"notice": {
  "event_id": "string",
  "run_id": "string",
  "state": "isolated | quarantined | corrected | released",
  "device_ids": ["string"],
  "reading_ids": ["string"]
}}
```

`reading_ids` is optional (default empty); the other fields are required and types are strict. Unknown extra fields are ignored. Accepted states: `isolated`, `quarantined`, `corrected`, `released`.

Replies:

- New event: `{"accepted": true, "invalidated": <count>, "committed_effects_unchanged": true}`
- Repeated `event_id`: `{"accepted": true, "duplicate": true}` (deduplication is in memory)
- Different run: `{"accepted": false, "code": "RUN_MISMATCH"}`

`isolated` and `quarantined` block the devices; `released` unblocks them but never revives old evidence, so corrected evidence must arrive with new reading IDs.

## `evaluate_tick` example

Input:
```json
{"batch":{"run_id":"r1","tick":1,"time":"2026-10-26T12:00:01Z","tick_seconds":1,"count":1,"readings":[{"run_id":"r1","reading_id":"r1-p1","tick":1,"timestamp":"2026-10-26T12:00:01Z","node_id":"POW-01","device_id":"POW-01.load_kw","sensor":"load_kw","channel":null,"value":60,"unit":"kW"}]}}
```
Output (no incident): `{"run_id":"r1","tick":1,"decisions":[]}`. Decisions carry `decision_id`, `status`, `reason`, original evidence IDs and a refusal code when blocked. Optional `lat`/`lon` are WGS84 degrees.

## Workflow: Twin → Brain → Guardian → Twin

1. Twin supplies discovery, readings, clock and containment state; Brain detects an incident.
2. Brain calls Guardian `describe_capabilities`, then `get_trust_verdict(reading_id, fresh=true)` for each reading individually.
3. Brain builds a typed plan, validates it, and calls Twin `preview_action` where required.
4. Brain calls Guardian `authorize_action` for the exact action.
5. Brain re-checks the Twin clock and containment, then calls Twin `actuate` with Guardian's original signed `g1` token, unchanged.

Brain never signs tokens and never performs containment. Twin keeps its own `get_capabilities`. Guardian tool names are exactly `describe_capabilities`, `get_trust_verdict` and `authorize_action`.

Guardian `authorize_action` receives `run_id`, `reading_ids`, `action`, `targets`, `params`, `risk_level`, `domain` and `idempotency_key`. Brain reads Guardian's `decision` (`approved` with a `token`, or `refused` with `refusal_code`) and `trust_score`. It accepts both the MCP `{"result":{...}}` wrapper and flat replies. A `pending` verdict (with `retry_after_ms` and `last_scored_tick`) is retried within a bounded window and never authorizes. [Exact mapping](docs/mock-team/GUARDIAN_CONTRACT.md).

## Time bases

- **Peer calls use real seconds.** Defaults: peer timeout 3 s, verdict wait 1.5 s, AI planning at most 60 s.
- **Freshness and token expiry use Twin simulated time.** Evidence age defaults to 10 simulated seconds (configurable, at most 60). A `g1` token must satisfy `iat <= Twin clock < exp` with `exp - iat` at most 60 simulated seconds.

## Run and configuration

From `brain`: `python -m civis_brain --env-file .env.partner`. Copy [partner template](config/partner.env.example), obtain credentials privately, and set `PEER_MODE=live`, `LLM_MODE=gemini`, `TWIN_FEED_ENABLED=true`, `GUARDIAN_TRANSPORT=mcp_v3`. Defaults: Twin `http://127.0.0.1:8000`, Guardian `http://127.0.0.1:5000`. Use one evaluation driver. Browser presets use isolated simulated peers.

## Scope and known limitations

- Capabilities: S01 signal R1, S02 virtual valve R3, S03 Power alert, S04 Air Quality alert, S05 one ambulance R2.
- The S02 policy permits only `WAT-01 → WAT-01`, `position: 40`, for Twin mock 3 seed 42. It is a virtual-command allowlist and does not model hydraulics. It is marked `fixture_only`, so a live run needs `MOCK_INTEGRATION_PROFILE=true` (set in the partner template).
- S06, S07 and S08 are disabled in the shipped scenario policy files.
- The current bounded service gate passes; wider Test Book acceptance and a teammate-attended live Gemini run remain separate.
- Brain keeps incident, deduplication and containment state in memory.
- Use the reviewed Guardian `main` subtree at `45e0ccb`, rather than the older bundled snapshot or `guardian_final_version`. Its verdict/authorization MCP tools and containment sender were exercised against Brain.
- Guardian uses `BRAIN_MCP_URL`, `BRAIN_GUARDIAN_CALLER_KEY` and `BRAIN_TIMEOUT_SECONDS=3` for containment. Its actual callback was observed after a confirmed Twin quarantine. The unrelated HTTP verdict webhook is not required.