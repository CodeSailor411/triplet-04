# Brain and Guardian integration contract

26 October 2026. CIVIS adopts the names and schema published in `guardian_mock_v3/guardian/INTERFACE.md`. Select `GUARDIAN_TRANSPORT=mcp_v3`. This replaces the old advisory-only description; it does not certify joint action acceptance. Older checkpoints remain reproducible in Git history.

## Existing MCP tools and mappings

Streamable HTTP, MCP protocol `2026-07-28`. Guardian's capabilities tool is `describe_capabilities`. Brain and Twin retain `get_capabilities`; the adapter's normalized internal operation is not a wire rename.

| Guardian wire | CIVIS normalization |
|---|---|
| `describe_capabilities({})` | `score_scale:1`; reading cutoff from `guardian_verdict_policy.trusted_min_inclusive`; R1-R3 from `risk_minimums` |
| `get_trust_verdict({reading_id,fresh:true})` | One call per original ID; `caused_by` must match; finite `trust_score` becomes `score`; `scale` must be `[0,1]` |
| `authorize_action({run_id,reading_ids,action,targets,params,risk_level,domain,idempotency_key})` | Original source IDs become `reading_ids`; risk becomes `risk_level`; domain follows the existing action; approved decision requires the original token; refusal preserves `refusal_code` |

`guardian_v3_scores` and `guardian_v3_approval` are internal port labels, not public tools partners must implement. Wire names are `get_trust_verdict` and `authorize_action`, as in the public environment template. Other transports are historical explicit selections, not automatic fallbacks.

Capabilities publish both reference `trust_cutoffs` and the inclusive verdict policy. CIVIS uses the latter rather than guessing floors. Guardian v3 publishes reading cutoff 0.7 and provisional action minima R1 0.5, R2 0.7, R3 0.85. A reading scored 0.65 is not trusted enough even for R1. CIVIS does not change these numbers or substitute a score.

## Readiness and clocks

Brain and Guardian ingest the real Twin stream independently. Brain never posts readings into Guardian during normal operation. Diagnostic tests that explicitly ingest data are separate from shipped-service acceptance.

Read-only fresh verdict retrieval retries explicit `GUARDIAN_VERDICT_NOT_READY` and generic `PEER_ERROR`, using the same IDs, at most three attempts and a bounded monotonic window. Default wait is 1.5 real seconds, clamped to half the outer peer timeout. An exhausted generic failure remains `PEER_ERROR`, cause unknown; it is never relabelled as not-ready. Denials, malformed replies and invalid scores remain terminal. Approval and actuation receive no additional retry from this adapter. Sanitized retrieval attempt counts are logged. Guardian should expose `verdict_not_found` through MCP `ToolError`; its current plain `ValueError` is hidden by MCP 2.3. A different structured availability schema needs explicit publication before use.

Peer timeout defaults to 3 real seconds. Recovery may request fresh scores for original and genuinely observed supporting evidence; it cannot manufacture observations. Evidence and token expiry use Twin simulated time. The mock profile permits evidence age up to 60 simulated seconds for AI latency, not an agreed physical safety threshold.

## Authorization and execution

Guardian owns its Ed25519 private key. It issues `g1.<payload>.<signature>`; Brain forwards that exact string. Brain checks binding to run, action, targets, parameters, evidence IDs, risk, key, issuer/audience and simulated validity. Twin verifies the signature with Guardian's public key, enforces its action/risk/cap policy, and consumes the token. No token translator or Brain signer exists.

An approval describes the exact command. A score is not permission. R3 Water retains local permitted-command validation, Twin preview and real Guardian authorization. `preview_action` checks virtual caps/containment, not hydraulic benefit. Missing Guardian preview support remains a partner blocker.

Repeated requests retain the operation key and receipt. Uncertain sends reconcile at most once with the original request/token after fresh checks. Changed payload under the same key is rejected. Restart requires a new run or explicit reconciliation.

## Credentials and containment

| Link | Matching variables |
|---|---|
| Brain → Guardian | Brain `GUARDIAN_BRAIN_KEY` = Guardian `GUARDIAN_BRAIN_MCP_BEARER_KEY` |
| Brain → Twin | Brain `TWIN_BRAIN_KEY` = Twin `TWIN_KEY_CITY_BRAIN` |
| Guardian → Brain | Brain `BRAIN_GUARDIAN_CALLER_KEY`, supplied privately |
| Twin → Brain | Brain `BRAIN_TWIN_CALLER_KEY`, supplied privately |

Guardian's API ingestion credential and Twin caller key differ from its inbound Brain MCP key. Guardian and Twin exchange the verification public key and compare fingerprints. Brain receives no private signing material.

Brain's existing `notify_containment({notice})` MCP callback is Guardian-only. It invalidates original reading IDs and affected devices and acknowledges duplicates. Notice fields are `event_id`, `run_id`, `state`, `device_ids`, optional `reading_ids`. State is `isolated`, `quarantined`, `corrected` or `released`, as in `contracts.ContainmentNotice`. Guardian performs real containment through Twin first. Brain also polls Twin's authoritative state before acting. Brain callback support does not mean Guardian has implemented its sender.

The current gate and exact partner defects are in [joint acceptance](JOINT_ACCEPTANCE_2026-10-26.md). Internal mocks do not establish interoperability.
