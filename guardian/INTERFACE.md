# Guardian interface | 9antra

**IMPLEMENTED AND TESTED LOCALLY:** Brain verdict/authorization, per-peer bearer checks, Twin ingestion/discovery, g1 token issue/verification, real in-process MCP 2.3.0 test peer. **PROPOSED / NOT JOINTLY TESTED:** partner schemas, preview, containment, notifications, Twin-side token verification.

Guardian evaluates and authorizes. It never executes actions or signs for Brain; Twin executes and enforces caps.

## Peer settings and authentication

Use a distinct bearer for each peer; never commit credentials.

| Link | Settings | Auth |
|---|---|---|
| Brain → Guardian MCP | GUARDIAN_BRAIN_MCP_BEARER_KEY | Bearer |
| Twin → Guardian API | GUARDIAN_API_BEARER_KEY | Bearer |
| Guardian → Twin | TWIN_BASE_URL, GUARDIAN_TWIN_BEARER_KEY, TWIN_MCP_TIMEOUT_SECONDS | Bearer |
| Guardian → Brain webhook | BRAIN_VERDICT_URL, GUARDIAN_BRAIN_BEARER_KEY | Bearer + idempotency |

Token settings: GUARDIAN_TOKEN_PRIVATE_KEY, GUARDIAN_TOKEN_PUBLIC_KEY, GUARDIAN_TOKEN_KID, GUARDIAN_TOKEN_ISSUER, GUARDIAN_TOKEN_AUDIENCE.

## Message examples

**1. Twin readings event** (supported local sensors: water_level, load_kw, congestion_index, pm25; envelope # CONFIRM with Twin).

    {"event":"readings","data":{"run_id":"r-42","readings":[{"run_id":"r-42","reading_id":"w-17","device_id":"W-1","timestamp":"2026-10-27T12:00:00Z","tick":17,"sensor":"water_level","value":68,"unit":"cm","lat":36.5,"lon":11.5}]}}

**2. get_trust_verdict** (fresh=false default). Pending has no score; scored reply includes trust_score, state, reasons, scale, cutoffs, history_requirement.

    {"request":{"reading_id":"w-17","fresh":false},"reply":{"status":"pending","reading_id":"w-17","retry_after_ms":500,"last_scored_tick":16}}

**3. authorize_action request** (MCP uses params; HTTP uses parameters).

Validation errors identify missing Guardian fields and show the accepted name for a known mismatch.

    {"run_id":"r-42","reading_ids":["w-17"],"action":"set_signal_plan","targets":["N-1"],"params":{"plan":"normal"},"risk_level":"R1","domain":"Traffic","idempotency_key":"r-42-w-17-plan"}

**4. Approval**

    {"decision":"approved","token":"<signed token>","token_id":"<id>","expires_at":1800000060}

**5. Refusal**

    {"decision":"refused","refusal_code":"action_not_in_twin_manifest"}

**6. Containment — PROPOSED only:** Guardian → Twin request for <Twin-confirmed operation> and <device_id>, with a stable idempotency key. Tool and fields # CONFIRM; no current route performs real containment.

## Verdict and risk policy

Score scale [0.0,1.0]; Trusted >=0.7, Degraded >0.3 and <0.7, Untrusted <=0.3. Action minima: R1 0.5, R2 0.7, R3 0.85. Statistical drift needs five prior readings; otherwise return insufficient_history and the minimum, without a score penalty. Tokens last 60 Twin-simulated seconds; get_clock is read for each issue and verification.
