# Guardian integration interface

## Status

**IMPLEMENTED AND TESTED LOCALLY:** Brain-facing Guardian MCP verdict/authorization tools; authenticated HTTP API; Twin SSE normalization/deduplication; thin Twin MCP discovery; g1 Ed25519 token binding; JSONL audit; canned discovery peer tests.

**PROPOSED / NOT YET JOINTLY TESTED:** Twin tool names/schemas, preview, capacity semantics, containment calls, notification acceptance, and Twin token verification. All unconfirmed names are marked in `src/guardian_config.py`. Authorization fails closed when required discovery or Twin clock is unavailable. R3/grid authorization refuses until safe preview is implemented.

## Peer configuration and authentication

Set distinct values in the process environment; do not commit secrets.

| Link | Settings | Authentication |
|---|---|---|
| Brain → Guardian MCP | `GUARDIAN_BRAIN_MCP_BEARER_KEY` | Bearer |
| Twin → Guardian ingestion/API | `GUARDIAN_API_BEARER_KEY` | Bearer |
| Guardian → Twin | `TWIN_BASE_URL`, `GUARDIAN_TWIN_BEARER_KEY` | Bearer |
| Guardian → Brain verdict webhook (optional) | `BRAIN_VERDICT_URL`, `GUARDIAN_BRAIN_BEARER_KEY` | Bearer + idempotency |

MCP uses Streamable HTTP. The SSE feed is separate. Peer MCP calls default to a **3 real-second monotonic timeout**. Token expiry is **60 simulated seconds**, based on Twin clock data; Guardian does not substitute its wall clock.

## Messages

**Twin readings event — implemented locally; partner envelope requires confirmation**

```json
{"event":"readings","data":{"run_id":"r-42","readings":[{
  "run_id":"r-42","reading_id":"w-17","device_id":"W-1","node_id":"W",
  "timestamp":"2026-10-23T12:00:00.000Z","tick":17,"sensor":"water_level",
  "channel":null,"value":68,"unit":"cm","lat":36.5,"lon":11.5
}]}}
```

Supported local sensor names: `congestion_index`, `water_level`, `load_kw`, `pm25`, `emergency_calls`. Unknown sensors and null readings are skipped. Emergency transcript/text fields are treated as data; they are not passed to command execution.

**Brain → Guardian verdict request/response — implemented**

Tool: `get_trust_verdict(reading_id, fresh=false)`.

```json
{"trust_score":0.91,"state":"Trusted","reasons":[],"caused_by":"w-17",
 "scale":[0.0,1.0],"cutoffs":{"trusted_min_inclusive":0.7,"degraded_min_exclusive":0.3}}
```

Fresh re-evaluation does not add another reputation penalty. Guardian returns evidence scores; it does not declare incidents.

**Brain → Guardian authorize — implemented locally, subject to Twin discovery**

```json
{"run_id":"r-42","reading_ids":["w-17"],"action":"set_valve_position",
 "targets":["W"],"params":{"position":20},"risk_level":"R3",
 "domain":"Water","idempotency_key":"r-42-w-17-valve"}
```

Approval returns a signed token, token ID, and expiry. Refusal returns a stable error code and no token. Token claims bind exact action, targets, params, idempotency key, reading IDs, key ID, and Twin-clock expiry. Guardian signs; Brain never signs. See [TOKEN.md](docs/TOKEN.md).

Current scores: Trusted `>=0.7`, Degraded `>0.3 and <0.7`, Untrusted `<=0.3`. Provisional minima: R1 `0.5`, R2 `0.7`, R3 `0.85`. Grid switching requires preview and token; until preview contract exists, Guardian refuses it.

**Guardian → Twin containment request — proposed, not implemented**

Tool name/schema require Twin confirmation. Intended fields include `run_id`, `device_id` or `node_id`, `action` (isolate/quarantine/rollback/release), and stable `idempotency_key`. No Guardian local simulation is evidence of Twin containment.

**Guardian → Brain containment notification — proposed, not implemented**

Transport, endpoint, payload, acknowledgment, and retry contract require CIVIS confirmation. Existing optional Brain webhook sends scored verdict summaries only.

## Policy and refusal codes

Action aliases: `set_failover → set_priority_mode`; `set_collection_priority → send_collection_truck`. Local Power cap 3 and Telecom/Waste rollback pool size 3 are offline fallback policy, never a claim about Twin capacity. Twin enforcement is authoritative.

Current explicit refusal conditions include `twin_discovery_unavailable`, `twin_sim_clock_unavailable`, `safe_preview_tool_unconfirmed`, `action_not_in_twin_manifest`, `risk_minimum_score_not_met`, and `action_not_allowlisted`. Exact partner codes for `CAP_EXCEEDED` and `DEVICE_QUARANTINED` need confirmation.

## Open confirmations

- **Twin:** confirm `list_actions`, `get_clock`, `list_nodes`, and `get_containment_state` names and schemas.
- **Twin:** preview tool, required inputs, returned preview ID, and validity rules.
- **Twin:** containment tool names, schemas, idempotency, cap/containment refusal codes, and state response.
- **Twin/CIVIS:** token audience, key ID registration, signature and one-time-use verification contract.
- **Twin/CIVIS:** cap schema and shared-node accounting; confirm whether Guardian should publish a pushed-score feed.
- **CIVIS:** approve Guardian Brain MCP tool names/schemas and containment-notification transport/payload/acknowledgment.
- **Policy owners:** approve final score cutoffs and R1/R2/R3 minimums.

