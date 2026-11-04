# Guardian interface | 9antra

**Guardian-side contract:** Bearer-authenticated Twin SSE ingestion, Twin MCP discovery, g1 Ed25519 action-token issue/verification, S02/S05 checks, and Twin containment calls followed by Brain `notify_containment`. Local tests use in-process peers or mocked partner effects; they do not verify a live Twin or Brain deployment.

Guardian evaluates and authorizes. It never executes actions or signs for Brain; Twin executes and enforces caps.

## Peer settings and authentication

Use a distinct bearer for each peer; never commit credentials.

| Link | Settings | Auth |
|---|---|---|
| Brain → Guardian MCP | GUARDIAN_BRAIN_MCP_BEARER_KEY | Bearer |
| Twin → Guardian API | GUARDIAN_API_BEARER_KEY | Bearer |
| Guardian → Twin | TWIN_BASE_URL, GUARDIAN_TWIN_BEARER_KEY, TWIN_MCP_TIMEOUT_SECONDS | Bearer |
| Guardian → Brain webhook | BRAIN_VERDICT_URL, GUARDIAN_BRAIN_BEARER_KEY | Bearer + idempotency |
| Guardian → Brain containment MCP | BRAIN_MCP_URL, BRAIN_GUARDIAN_CALLER_KEY | Bearer; key matches Brain's configured caller key; calls `notify_containment` after a confirmed Twin effect |

Token settings: GUARDIAN_TOKEN_PRIVATE_KEY, GUARDIAN_TOKEN_PUBLIC_KEY, GUARDIAN_TOKEN_KID, GUARDIAN_TOKEN_ISSUER, GUARDIAN_TOKEN_AUDIENCE. The Twin feed has no signed-reading field or canonicalization contract in tag `twin-mock-3`; feed authentication is Bearer-based. Ed25519 `g1` signatures are for Guardian action tokens, which Twin verifies with Guardian's configured public key.

## Message examples

**1. Twin readings event** (supported sensors include water_level, load_kw, congestion_index, pm25, emergency_calls, and units_free; the Twin SSE feed is Bearer-authenticated).

    {"event":"readings","data":{"run_id":"r-42","readings":[{"run_id":"r-42","reading_id":"w-17","device_id":"W-1.water_level","node_id":"W-1","timestamp":"2026-10-27T12:00:00Z","tick":17,"sensor":"water_level","channel":null,"value":68,"unit":"cm","lat":36.5,"lon":11.5}]}}

**Channelled evidence:** `emergency_calls` uses `channel=medical` for S05 incident evidence. `units_free` uses `channel=ambulance`, `unit=units`; Guardian retains that reading ID and checks it against Twin's current `get_readings(node_id=<dispatch-carrier>, sensor=units_free)` result before authorizing. If Twin advances one tick between SSE delivery and authorization, Guardian accepts the trusted evidence only when the current count is unchanged.

**2. get_trust_verdict** (fresh=false default). Pending has no score; scored reply includes trust_score, state, reasons, scale, cutoffs, history_requirement.

    {"request":{"reading_id":"w-17","fresh":false},"reply":{"status":"pending","reading_id":"w-17","retry_after_ms":500,"last_scored_tick":16}}

**3. authorize_action request** (MCP uses params; HTTP uses parameters).

Validation errors identify missing Guardian fields and show the accepted name for a known mismatch.

    {"run_id":"r-42","reading_ids":["w-17"],"action":"set_signal_plan","targets":["N-1"],"params":{"plan":"normal"},"risk_level":"R1","domain":"Traffic","idempotency_key":"r-42-w-17-plan"}

**4. Approval**

    {"decision":"approved","token":"<signed token>","token_id":"<id>","expires_at":1800000060}

**5. Refusal**

    {"decision":"refused","refusal_code":"action_not_in_twin_manifest"}

**6. S02 valve authorization:** Guardian accepts only `set_valve_position`, Water/R3, target `WAT-01`, `{"position":40}`. Twin's manifest must report `preview_required=true` and `preview_enforced=true`. Brain performs Twin `preview_action` for this exact command. Preview state is caller-scoped to Brain; Twin enforces the 60-tick, one-commit limit when Brain calls `actuate`. Guardian does not create a preview or send a `preview_id`.

**7. S05 dispatch authorization:** Guardian accepts Emergency/R2 dispatch to the discovered dispatch carrier with `unit_type=ambulance`, `units=1`, and `destination` equal to the node on the primary `medical` incident reading. `reading_ids` must include both the incident reading and the trusted ambulance `units_free` reading from that carrier. Guardian requires the latest ID or a one-tick-old ID when Twin reports the same unit count; it rejects a Twin reading whose own tick trails the batch by more than one. Twin dispatch preview is not required by this tag.

**8. Containment:** Guardian calls Twin `isolate_sensor` or `quarantine_device` with `device_ids`, optional `reason`, and `caused_by`; `rollback_reading` with `reading_ids` and `caused_by`; or `release_device` with `device_ids` and `caused_by`. Twin has no containment `idempotency_key`; these operations are repeat-safe. After Twin confirms an effect, Guardian calls Brain MCP `notify_containment` with exactly one argument, `notice`: `{"event_id":"<stable event id>","run_id":"<Twin run id>","state":"isolated|quarantined|corrected|released","device_ids":["..."],"reading_ids":["..."]}`. The `state` value is mapped from the confirmed Twin tool; raw tool/status fields are not sent. Authorization uses `Bearer <BRAIN_GUARDIAN_CALLER_KEY>`.

**9. Signature policy:** `GUARDIAN_REQUIRE_READING_SIGNATURES` is a server setting, not a reading field. Callers cannot turn it off per request, and any supplied reading signature is validated. The Twin SSE feed is Bearer-authenticated and unsigned; Guardian's Ed25519 `g1` action-token signature is always verified.

## Verdict and risk policy

Score scale [0.0,1.0]; Trusted >=0.7, Degraded >0.3 and <0.7, Untrusted <=0.3. Action minima: R1 0.5, R2 0.7, R3 0.85. Statistical drift needs five prior readings; otherwise return insufficient_history without a score penalty. Tokens last 60 Twin-simulated seconds; get_clock is read for each issue and verification. `units_free` has deterministic Guardian scoring; the current RF artifact has no corresponding model feature and returns an unavailable advisory.
