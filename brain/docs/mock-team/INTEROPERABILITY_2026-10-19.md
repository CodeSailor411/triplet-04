# CIVIS interoperability review

Started 19 October; completed 20 October 2026. Branch: codex/civis-elyes. Only files under brain/ are changed.

## Result

CIVIS's clock, feed, incident identity and preview problems are fixed and covered by regressions. Water and Medical commit against the real, advancing Twin using an explicitly simulated Guardian. Power and Air Quality produce their reduced alerts. Traffic reports its missing metric. A successful real three-layer actuation is still blocked by Guardian's missing authorization interface.

Passing blocker tests mean the problem was reproduced and Brain refused safely. They do not mean the missing partner functionality passed acceptance.

## Sources tested

| Source | Revision |
| --- | --- |
| CIVIS branch before changes | 953f17baf70a55dc715ab46e83ce3a7b00339ae3 |
| Published brain-mock-1 commit | f3cc67e3f66fd19d5d3dbc957b98f4b742a08b65 |
| Latest fetched main for Twin and Guardian | cf6f1dcb25796e64d22e96b3fe6ab8779f00a0b0 |
| Published twin-mock-1 commit, retained as historical reference | 9170ee2404face946a346711e1739d0c405052c1 |

Current Twin and Guardian were extracted into an ignored local partner snapshot. Neither partner's source was edited. This review also uses the 16 October meeting, sensor table v1.3 and CIVIS architecture one-pager. Where the meeting and code differ, the mismatch is recorded instead of assuming planned tools already exist.

## CIVIS changes

| Problem | Change and test |
| --- | --- |
| Any Twin tick advance blocked execution | Accept consistent advancing clocks within a configured evidence-age bound. Obtain a fresh clock before authorization and before execution. Real Twin test: evidence tick 1, authorization at a later tick, one committed dispatch. |
| No independent continuous feed | Authenticated SSE receiver and separate decision worker. Bounded queue, explicit gap/overflow/reconnect handling, feed status in /health. Real feed tested during delayed Medical planning. |
| Reusing an action key across separate incidents suppressed later responses | Key includes the incident episode. Tests cover Traffic, Water and Medical clearing then recurring, each with a distinct key. Persistent incidents and missing-data gaps keep the original operation. |
| Pending waited for a later evaluation | Confirm immediately when a configured tool is advertised. One retry after transport uncertainty, original key and bounded real-time deadline. Unit/contract tests only: actual Twin does not expose this tool yet. |
| Preview used an invented safe flag and extra arguments | Use Twin's exact action/targets/params request and would_pass_checks/blocked_by reply. Verify binding and expiry. Keep separate Water topology requirements. |
| Percent symbol and GPS fields were lost or rejected | Accept % and percent; retain original unit and lat/lon. Reject invalid coordinates. Additional discovered domains no longer invalidate the existing five scenarios. |
| Lost reply could trigger another authorization | One reconciliation attempt with the original request/token/key; no new authorization. Overlapping unresolved operations block. Wrong-operation receipts remain unconfirmed. |
| New readings could invalidate a plan while Gemini worked | Latest feed can withdraw a cleared incident, missing evidence or insufficient ambulance availability. Gap, disconnect, reset and containment invalidate in-flight plans. |
| Fixture thresholds prevented explicit partner-mock testing | Add opt-in MOCK_INTEGRATION_PROFILE and local policy overrides. Defaults remain cautious. No setting supplies fake approval in live mode. |
| Shared log correlation was incomplete | Log Guardian token ID and actual incident operation key, with full tokens and secrets redacted. |

## Scenario outcomes

The control runs use actual Twin readings, its public scenario fault tool, actual MCP transport and its real clock. The planner is recorded test data. The test Guardian supplies synthetic approval. Its approval of deliberately injected readings tests plumbing, not real threat detection.

| Scenario | Observed outcome | Acceptance boundary |
| --- | --- | --- |
| S01 Traffic | Clear alert that congestion_index is unavailable; zero actuation | Positive signal workflow passes local contract tests. Native Twin positive scenario awaits the metric or an agreed conversion. |
| S02 Water | High-water candidate, configured test valve choice, real preview, exact token, one real Twin commit | Test topology is explicit. No claim that cap/quarantine preview proves a physically safe valve direction. Real Guardian approval still missing. |
| S03 Power | Evidence-based reduced alerts; zero grid actions | Fixture thresholds are test-only. Normal service defaults still have no approved overload threshold. No invented outage or grid-switch implementation. |
| S04 Air Quality | Persistent-pollution alert over actual SSE; zero actuator calls | Alert flow works with test trust. Real Guardian scores remain unavailable. |
| S05 Medical | Actual emergency call and ambulance readings, exact dispatch, one real Twin commit | Works with test authorization, including a moving clock and reception during planning. Real Guardian cannot yet issue the token. |

## Remaining partner blockers

| Owner | Evidence | Required next step |
| --- | --- | --- |
| 9antra | Actual MCP inventory contains only describe_capabilities and evaluate_reading_advisory. No exact-action authorization token is issued. | Deliver authenticated evidence assessment, numeric cutoffs and exact-action authorization, then confirm the mapping in GUARDIAN_CONTRACT.md. RF probability is not a trust verdict or permission. |
| 9antra | Native Twin water reading submitted to /ingest returns HTTP 422. Guardian expects a different ingestion schema. | Implement its Twin ingestion adapter and feed integration, preserving run/reading/device IDs, time, units and lat/lon. |
| 9antra | Its published interface explicitly describes Brain outputs and containment as simulations. | Connect real Guardian containment to Twin and notify_containment to Brain; test rollback invalidation and release end to end. |
| Trinity | Current readings still have no congestion_index; no commit_action is advertised. | Deliver the Traffic metric and the pending/confirmation contract, or explicitly keep two-step disabled. |
| Joint | No real Guardian signing key, score policy or approval stream is available in this checkout. | Supply these and run signed authorization and containment across the actual three services. |
| Joint | Water safe direction and live numeric thresholds are not proven by a successful dry run. | Provide reviewed per-location choices and detection policy. Do not infer physical safety from would_pass_checks. |

### Partner security acceptance failures reproduced on 20 October

Nine checks in interop/test_partner_acceptance.py give **one passing control and eight failures**. These are required-behavior assertions, not skipped tests or expected-failure markers.

| Owner | Failed boundary | Observed result | Required correction |
| --- | --- | --- | --- |
| Trinity | Future iat | A correctly signed token issued 30 seconds in the future committed | Reject tokens that are not yet valid |
| Trinity | Excess token lifetime | A correctly signed 120-second token committed | Enforce the agreed maximum 60 simulated seconds |
| Trinity | Score range | Correctly signed score 2.0 and NaN tokens both committed | Require a finite score in 0..1 before applying risk floors |
| Trinity | Empty token ID | A correctly signed token with empty jti committed | Require a nonempty token identity before consumption |
| 9antra | Missing authentication | Unauthenticated quarantine mutation returned HTTP 200 | Authenticate and authorize state-changing routes |
| 9antra | Rollback invalidation | Rolled-back reading still returned trust_score=1.0 and trusted | Withdraw cached verdicts for invalidated evidence |
| 9antra | Signature policy controlled by caller | The same invalid HMAC got 401 with require_signature=true and 200 with false | Set verification policy on the service, not from untrusted input |

The Twin tests use a local Ed25519 test signer. They demonstrate missing claim validation, not a forged-signature bypass. Valid-signature and invalid-signature controls work. Brain independently rejects the five invalid claim variants before actuate. Guardian and Twin sources remain unchanged; these failures require their owners.

## Remaining CIVIS limits

- The full neighbour-first, next-sensor-tick, fresh-verdict recovery sequence is not integrated. Existing attempts are bounded across evaluated ticks. Guardian has no usable evidence-assessment contract to validate that sequence against. Do not describe it as completed or reinterpret unrelated neighbour values as proof.
- The maximum evidence age defaults to 10 simulated seconds. This is an explicit CIVIS mock safeguard, not a triplet-agreed threshold. Gemini may take up to 60 real seconds; an old result is rejected. The team should agree the required freshness versus latency budget.
- Operation state is in memory. Restart into a fresh Twin run, and reconcile uncertain effects first. Automatic same-run recovery across a process restart is not implemented.
- Real Gemini was not called in these integration runs. Recorded plans make them repeatable; the existing suite exercises Gemini parsing/validation with recorded HTTP responses.
- Grid switching remains outside the five-scenario reduced response. CIVIS refuses unsupported grid plans; it does not claim the requested final-version grid workflow has been added.
- The original architecture's unsigned-to-signed transition and two-step behavior still require actual partner joint acceptance. Full readiness remains false.

## Verification

Final counts are recorded with the local JUnit results:
- Brain regressions: .artifacts/interop-oct19/brain-junit.xml.
- Partner checks: .artifacts/interop-oct19/partner-junit.xml.
- Required partner security acceptance: .artifacts/interop-oct19/acceptance-junit.xml, eight failures retained.
- Sanitized scenario outcomes, MCP inventory and three-layer blocker: .artifacts/interop-oct19/*.json.

Final verification on 20 October:

- **312 Brain tests passed**, including all five invalid token-claim variants rejected before actuation.
- **12 partner integration/control checks passed**, including the actual moving Twin clock and SSE reception during planning. Tests explicitly preserve the real Guardian blocker.
- **6 additional Twin controls passed**: unsigned approval, denial, valid Ed25519 signature, invalid signature rejection, unconfigured-preview refusal and missing-Traffic-metric handling. Committed cases also checked duplicate replay, changed-request conflicts, token reuse and Twin's log merger. These older controls use an explicitly frozen clock; the 12 newer checks use the running clock.
- **Partner security acceptance: 1 passed, 8 failed**, detailed above. Full three-layer acceptance is not green.
- Ruff and Git whitespace checks passed. Installed startup and the plain developer console returned HTTP 200.
- All **120 archived partner files remained byte-for-byte unchanged** after testing.
- Python 3.12.13; MCP 2.3.0; FastAPI 0.142.2; Uvicorn 0.54.0; Pydantic 2.13.5; pydantic-settings 2.15.0; sse-starlette 3.5.0; cryptography 50.0.2; pytest 9.1.1; pytest-asyncio 1.4.0. These agree with the applicable 16 October pins. Brain does not import PyYAML; the separate Twin environment uses its own declared requirement.

No remote push, merge or tag is part of this local change.

## Run and reproduce on Windows

From this checkout's brain directory:

~~~powershell
.\.venv\Scripts\python.exe -m civis_brain
~~~

Open http://127.0.0.1:8001/ for isolated developer cases. Defaults use local fixtures. To run the unit/contract suite:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests mocks scripts interop
~~~

For the untouched partner checks, follow interop/README.md. Do not turn on GUARDIAN_CONTRACT_CONFIRMED merely to bypass a blocker. A three-layer deployment needs the missing real contract first.
