# Brain and Guardian integration contract

20 October 2026. This is the implemented Brain adapter contract for partner review. Guardian_Unified is uploaded, but its MCP server exposes RF advisory tools and no exact-action token issuer. Keep the mapping unconfirmed until its actual assessment and authorization interfaces are delivered. See INTEROPERABILITY_2026-10-19.md for the current test evidence.

## Requests and responses

MCP Streamable HTTP, pinned protocol 2026-07-28. Every private call uses the receiving service's Bearer credential. Brain uses a numeric evidence assessment and a separate exact-action authorization.

| Operation | Brain sends | Brain expects after mapping |
| --- | --- | --- |
| Capabilities | {} | protocol_version, positive score_scale, thresholds with reading, R1, R2, R3 |
| Assess evidence | run_id, tick, readings with original IDs, values and units | scores: exactly one {reading_id, score} per requested reading |
| Authorize action | run_id, tick, time, action, targets, params, risk, source_reading_ids | approved: true and token, or approved: false and an optional code |
| Containment callback to Brain | notify_containment({notice}) | accepted, duplicate indication when applicable |

time is simulated UTC from Twin, not the computer clock. Scores are finite numbers in the advertised scale, never labels or booleans. A score does not authorize an action. Missing or malformed required fields block the action.

See config/guardian-mapping.example.json. Replace the two placeholder tool names and field paths only after Houssem confirms his schemas. Request mappings rename top-level fields; response paths support nested objects. response_fields are required; optional_response_fields let a refusal omit a token. Use one mapping for approval and refusal. Configure GUARDIAN_SCORE_TOOL, GUARDIAN_TOKEN_TOOL, GUARDIAN_MAPPING_FILE and then GUARDIAN_CONTRACT_CONFIRMED=true. This setting records team confirmation, not a test result.

## Credentials and permissions

| Variable in Brain's ignored .env | Issuer and recipient |
| --- | --- |
| BRAIN_TWIN_CALLER_KEY | Elyes supplies to Dali if Twin calls Brain |
| BRAIN_GUARDIAN_CALLER_KEY | Elyes supplies to Houssem for calls to Brain |
| BRAIN_SCENARIO_KEY | Elyes supplies to the authorized scenario driver |
| TWIN_BRAIN_KEY | Dali supplies; must match Twin's TWIN_KEY_CITY_BRAIN |
| GUARDIAN_BRAIN_KEY | Houssem supplies for Brain calls to Guardian |

Run python scripts/setup_peer_keys.py with Brain's virtual environment to generate only missing/default inbound credentials. Custom keys and the Gemini key are preserved; no secret values are printed. Exchange credentials privately. Do not put keys in this document, release notes, command arguments or Git.

All three authorized callers may evaluate batches and read incidents/decisions. Only Guardian may notify containment. Brain never calls Guardian-only isolation, quarantine, rollback or release operations on Twin.

## Tokens and duplicate execution

Guardian owns the signing private key; Twin receives its public key and verifies the signature. Brain forwards the original token and checks exact action/targets/params, run, issuer/audience, token ID, normalized score and simulated validity. It never signs a real approval.

Current Twin draft fields: iss, aud, jti, run_id, iat, exp, action, targets, params, score. The score is 0..1. Maximum lifetime is 60 simulated seconds. Unsigned mode is an explicit mock option; it is not cryptographic authentication. Ed25519 signatures are supported by Twin and tested using a test Guardian.

The draft uses RFC3339 strings for iat and exp. This is a custom JWS payload, not strict RFC 7519 JWT claims: JWT requires numeric NumericDate values for these fields. Agree custom claims or migrate both peers together; do not change one side silently. References: [JWS compact serialization](https://www.rfc-editor.org/rfc/rfc7515.html#section-3.1), [JWT expiration](https://www.rfc-editor.org/rfc/rfc7519.html#section-4.1.4), [JWT issued-at](https://www.rfc-editor.org/rfc/rfc7519.html#section-4.1.6).

The same run/scenario/incident episode/normalized command keeps the same idempotency key. A confirmed clear followed by a new incident starts a new operation. Duplicate ticks return their saved result. Lost confirmation remains pending with the original key. A changed command needs a new key and new approval. State is in memory: use a fresh run after restart or reconcile uncertain outcomes first. Logs do not restore execution state.

## Still requiring agreement and joint testing

- Real Guardian discovery, verdicts, tokens, errors and callback wiring.
- Pushed Guardian verdict stream: not implemented. Current Brain requests assessments.
- Live recovery is implemented against this adapter: matching neighbour readings, a later tick of the same sensors within 3 real seconds, then a fresh assessment of original plus supporting evidence. Total recovery budget is 10 real seconds. Guardian must return one score for every requested reading, including historical IDs. It must reassess the originals rather than treating a neighbour as permission. No missing observations are fabricated. This remains to be accepted against real Guardian.
- Brain now confirms immediately when the configured tool is advertised, with a 10-real-second budget from send and at most one same-key retry. Actual Twin commit_action is absent, so joint confirmation and the Guardian reaction target remain unverified.
- Advancing-clock and concurrent SSE tests pass against real Twin with recorded plans and a test Guardian. The partner mock environment allows 60 simulated seconds of evidence age; the developer default is 10. Long Gemini plans may still be refused. The team must agree the final freshness and reaction-time policy.
- Traffic still needs congestion_index or an agreed conversion. Current Twin preview is integrated and tested; Water still requires explicitly reviewed safe topology.
