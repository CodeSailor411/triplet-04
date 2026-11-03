# Tagged mock v2 integration audit

23 October 2026. Branch: `codex/civis-elyes`. This audit covers the current five reduced CIVIS workflows, not the planned eight-incident upgrade.

**Result: full three-layer acceptance is blocked.** Real data and verdict exchange are exercised. No successful physical action using an actual Guardian approval is claimed.

## Exact sources

| Layer | Tested revision |
|---|---|
| CIVIS starting point | `brain-mock-2`, commit `1ff1553e1423682e244c5e3ba330bd7cf00ada51`, plus local Brain fixes in this audit |
| Trinity | `twin-mock-2`, commit `9cc2ab02ff30462061169fb3c0ca4e8003aa52d1` |
| 9antra | `guardian_mock_v2`, commit `6482a4601872e2449cc30e0e0edc02421e38a96e` |

Only `twin/` and `guardian/` were imported from their respective tags. All 126 imported files match the tagged bytes. Previous local folders are backed up under `.interop/oct23/original-folders/`. No partner source was edited. No tag or remote branch was changed by this audit.

The exact Guardian tag fails before startup: `src/app.py` expects `guardian/models/model_metadata.json`, but the file is at `guardian/src/models/model_metadata.json`. The bundled layer path in `integration_service.py` has the same relocation problem. Deeper tests use a clearly identified separate copy under `.interop/oct23/guardian-diagnostic/`, with tagged `models/` and `guardian_layer/` duplicated at the expected legacy paths. Source bytes remain unchanged. This workaround is not proof that the distributed tag starts successfully.

## Workflow and scenario evidence

Twin runs with an advancing clock at speed 1. Actual authenticated SSE supplies inputs; MCP supplies discovery, clock, preview and action calls. The separate Guardian bridge consumes actual Twin SSE. CIVIS reads actual Guardian HTTP evaluations through an optional adapter. Its protocol/transport is documented separately from Guardian's model-advisory MCP endpoint.

| Workflow | Observed result using actual Guardian |
|---|---|
| S01 congestion | Twin supplies `vehicle_count` (`cars/min`) and `avg_speed` (`km/h`). CIVIS currently expects `congestion_index` (%), so it warns and does not signal. This is an input-policy mismatch; no conversion is invented |
| S02 high water | Native evidence accepted; test-configured valve choice reaches real Twin preview; CIVIS blocks the incompatible signed approval contract |
| S03 Power | Evidence-based reduced alerts; grid switching remains outside this reduced response implementation |
| S04 Air Quality | Sustained pollution produces the intended alert; no AQ actuator or unsupported emergency dispatch |
| S05 Medical | Blocked: Guardian rejects same-tick medical channel as replay. Resource availability scoring is also unsupported |

All five observed zero unauthorized Twin effects. Passing these blocker checks demonstrates safe handling, not five successful positive action workflows. Additional positive controls use an explicitly labelled test Guardian and are reported separately.

Twin's public scenario tool injects reported-value faults, stuck sensors and replay; it does not create independently verified physical floods or medical incidents. The Water test choice is synthetic topology configuration. Those controls do not establish hydraulic safety or prove the sensor report is a genuine physical incident.

## CIVIS changes

- Added optional `GUARDIAN_TRANSPORT=http_v2` support using existing Guardian endpoints. Existing MCP mode remains available. No new public API or signing service was introduced.
- Reads the partner's explicit published trust policy; preserves its strict `score > 0.7` reading boundary. Provisional risk settings require the explicit mock profile.
- Verifies source ID, device, sensor type, tick, timestamp, original value/unit and coordinates before using a returned evaluation. Synthetic, rejected or mismatched evidence blocks the decision. Missing evaluation-window entries produce a clear refusal.
- Requires a fresh joint run after a run-ID change because current Guardian evaluations lack run binding. No fabricated scores, duplicate ingestion or rewritten approval tokens.
- Preflight identifies HTTP evidence support, provisional policy and unavailable compatible action authorization separately.
- Redacts `g1` approval tokens in free-text logs as well as structured token fields. Added adapter regression and tagged-peer tests.

## Partner corrections needed

| Owner | Problem and reproduction | Required correction |
|---|---|---|
| 9antra | Exact tag fails at `python guardian/src/run.py` | Resolve models and bundled-layer paths from the actual published layout; verify a fresh clone |
| 9antra + Trinity | Real Ed25519 Guardian token is valid under Guardian's own public key but Twin rejects it as `TOKEN_INVALID` | Agree one signed contract: Guardian `g1`, `token_id`, `parameters`, `trust_score` differ from Twin JWS, `jti`, `targets`, `params`, `score`. Include exact targets and use Twin simulated UTC time. Do not translate an already signed token in Brain |
| 9antra | Each 109-reading Twin batch produces 50 evaluations and 59 unsupported skips; 18 emergency-channel readings are falsely rejected as replay | Preserve channel identity and use appropriate per-channel sequence tracking. Add the required `units_free` and other sensor semantics, or agree explicit exclusions without breaking evidence needed for decisions |
| CIVIS + Trinity agreement | CIVIS S01 expects an index, while Twin provides native count and speed | Prefer adapting CIVIS to native `vehicle_count` and `avg_speed` under an agreed detection policy. An explicit derived index is optional, not a required new Twin API. Do not invent live thresholds or conversions |
| 9antra | Authorization accepts a verdict from one run with another requested run ID | Store and enforce run identity for readings, verdicts, replay state and approval; define reset behaviour |
| Trinity | Five invalid signed-claim variants still commit: future issued-at, excessive lifetime, score above one, NaN score, empty token ID | Validate time ordering/lifetime and finite bounded scores; require nonempty single-use IDs before execution |
| 9antra | Legacy mutations are unauthenticated; rollback leaves a trusted old verdict; caller can disable signature requirement | Protect mutation paths, invalidate corrected evidence, make signature policy server-controlled. New ingestion endpoint authentication does pass |
| 9antra | Audit records lack event_id, tick and layer and use wall time; shared Twin timeline reader discards them | Emit the agreed simulated-time event envelope and retain wall time separately |
| 9antra | Quarantine endpoint explicitly reports `simulated: true`; actual Twin containment does not change | Invoke Twin containment with Guardian's own credential and correlate the resulting Brain invalidation. Do not advertise local reputation changes as physical/shared containment |

Current Guardian Power policy also counts authorizations per run; Twin action caps are per-request node limits. Agree their relationship before enabling grid actions. Current Guardian risk minima are marked provisional in its own policy file.

## Reproduce and interpret the results

From the repository root, the exact-tag startup check intentionally stops on Guardian's packaging defect:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/test_tagged_v2.ps1
```

To reproduce deeper tests with the documented diagnostic layout:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/test_tagged_v2.ps1 -DiagnosticGuardianLayout
```

Add `-LiveGemini` for an explicit external request using the existing private `brain/.env`. Ordinary tests use recorded planning to isolate contracts; no fake Guardian is used in `test_v2_joint.py`. The script installs an isolated Python 3.12 integration environment using declared partner requirements and the existing Brain lock. It generates local test signing keys under ignored `.artifacts`, never in source.

Required partner acceptance failures remain ordinary failing assertions. The script returns a failure status until those behaviours are corrected; they are not skipped or marked expected failures. Current counts and sanitized evidence are recorded in the accompanying validation summary.

## Remaining acceptance gate

Start the unmodified published Guardian, receive both live feeds, obtain correctly bound actual Guardian verdicts and compatible signed approvals, execute supported actions exactly once, propagate actual containment, and merge all three event logs. Verify normal, attack/refusal, stale-data, reconnect, duplicate-request and partner-failure cases. Preserve clear boundaries when a capability or reviewed topology is absent.

The current evidence supports continued joint debugging. It does not support declaring the final architecture, all physical response types or the future graph/eight-incident work complete.

## Traffic and current-code recheck

On 23 October, a real MCP `get_readings(domain="traffic")` call returned 22 readings covering `vehicle_count` (`cars/min`) and `avg_speed` (`km/h`). A `get_readings(sensor="congestion_index")` call returned `UNKNOWN_SENSOR`. Twin README and MCP module comments mention the index as planned, not implemented. Earlier wording that Twin has no Traffic metric was incorrect.

After fetching GitHub, `twin-mock-2`, `origin/main` and `origin/twin-integration-tip` have the identical `twin/` tree `5666e5a75b86ac42573c3300997e8f17e305660b`. The six signed-claim checks were rerun: the valid control passes, and all five invalid variants still incorrectly commit. The signer is a local test signer, not an actual Guardian authorization. This verifies Twin claim validation independently of the Guardian token-format mismatch.

A newer `guardian_mock_v3` tag was discovered during this recheck. The Guardian findings above apply to the frozen v2 source only; v3 has not been integrated or tested by this audit.
