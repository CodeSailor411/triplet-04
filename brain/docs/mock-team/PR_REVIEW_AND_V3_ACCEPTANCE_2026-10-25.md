# CIVIS PR review and tagged v3 acceptance

25 October 2026. Development branch `codex/civis-elyes`. All integrations are local. `main` and published `brain-mock-2` are unchanged.

## Member review

| PR | Delivered | Review outcome |
|---|---|---|
| [17, Yassine](https://github.com/CodeSailor411/triplet-04/pull/17) | S06 explicit accident detector and tests | Integrated locally. Its stale S01/runtime description needs updating. Live report convention and response are not agreed; alert-only behavior is explicit. |
| [19, Maram](https://github.com/CodeSailor411/triplet-04/pull/19) | S08 detection and six provisional fixture cases | Integrated locally. Shared Fire dispatch helper is now available, but her submitted planner is still empty. Reject non-confirmation values. Replace provisional resource type/channel with `fire`. Fix the changing payload under one reading ID and separate event identity. PR base should be Elyes, not main. |
| [20, Mariem](https://github.com/CodeSailor411/triplet-04/pull/20) | S07 detector, constrained planner and Water cases/tests | Integrated locally. Fixed the real shared registration/action-kind/policy-direction gaps. Removed the workflow skip. Live supply metadata and datum remain partner prerequisites. |

See `ELYES_SHARED_CORE_2026-10-25.md` for the helper signature and exact next steps. New member-owned configuration paths are included in the central ownership policy.

## Exact partner source

| Layer | Tag | Commit |
|---|---|---|
| Trinity Twin | `twin-mock-3` | `b012c94e4a63652c7fbe9b6baf62ce59b4a1ac9c` |
| 9antra Guardian | `guardian_mock_v3` | `526f8f64970ded02319cf0763cf03a8159f085f0` |

Extracted 72 Twin and 101 Guardian versioned files into `.interop/oct25/`. No partner source patch or asset-layout workaround was used. The isolated combined environment uses Python 3.12.13 and the declared Brain/Twin/Guardian requirements. Test signing keys are local and ignored. Their use is labelled separately from actual Guardian approval.

## Confirmed improvements

- Twin publishes `congestion_index` in percent through actual MCP.
- All six signed JWS controls pass: valid request accepted; future issue time, excessive lifetime, score above one, NaN score and empty token ID refused. The five earlier Twin failures are fixed in this tag.
- A correctly signed `g1` request is accepted by actual Twin using an explicit test signer. This proves wire verification for that control, not that Guardian authorized an incident.
- Exact Guardian v3 starts, exposes `describe_capabilities`, `get_trust_verdict`, `authorize_action`, and returns an actual fresh verdict for a native Twin congestion reading. CIVIS now adapts these names and the published inclusive trust cutoff.
- Actual S03 alert and S04 sustained-PM2.5 alert workflows pass with real Guardian evidence. Power alerts do not certify the unfinished switching workflow.
- Guardian now rejects the tested unauthenticated legacy quarantine mutation. The other two prior legacy security failures remain, as listed below.

## Actual five-workflow results

These tests use actual tagged peers and a recorded test planner. Native Twin readings are forwarded unmodified to Guardian's existing authenticated ingestion endpoint. They do not use live Gemini or substitute Guardian scores/tokens.

| Scenario | Result | Evidence |
|---|---|---|
| S01 congestion | Blocked | Actual Guardian refuses authorization with `twin_discovery_unavailable`. Tested on a single-domain carrier to isolate authorization from the shared-node cap issue. |
| S02 high water | Blocked | Actual Twin preview is reached, then Guardian refuses authorization with `twin_discovery_unavailable`. The test's valve mapping is explicitly synthetic, not reviewed live hydraulic topology. |
| S03 Power | Alert | Actual trusted Power candidates produce explained alerts. Safe switching remains unfinished. |
| S04 Air Quality | Alert | Sustained PM2.5 produces the expected alert with actual Guardian evidence. |
| S05 Medical | Blocked | Guardian skips `units_free`; its verdict tool fails for the missing availability verdict. CIVIS blocks without requesting an unsupported dispatch. |

S06-S08 live acceptance is not claimed. S07 passes offline workflows; Fire shared positive/refusal paths pass with a clearly labelled test wrapper. Maram's real submitted Fire planner remains incomplete.

## Required corrections

| Owner | Finding | Required correction |
|---|---|---|
| 9antra | Native Twin discovery fails in `src/twin_adapter.py:191`: MCP 2.3 yields two streams, but Guardian unpacks three. Actual exception: `ValueError: not enough values to unpack (expected 3, got 2)`. | Adapt its client to the declared MCP version and run discovery against real Twin, then retry authorization. CIVIS's read-only discovery diagnostic reproduces the failure unchanged. |
| 9antra | Native `units_free` readings have no Guardian mapping. The verdict tool then has no availability verdict. | Define and score availability evidence, preserving `ambulance`/`fire`/`police` channels and units; never invent a score in Brain. |
| 9antra | After authenticated rollback, the legacy verdict endpoint still returns the original `trust_score: 1.0` and trusted state. | Invalidate the prior verdict across every supported read/authorization path when its reading is withdrawn. |
| 9antra | Authenticated legacy ingestion refuses an invalid signature when `require_signature=true` (401), but accepts the same bad signature when the caller sets false (200). | Make required signature validation a server policy rather than a caller-controlled downgrade. |
| 9antra | Static follow-up: authorization reads manifest item `name`, while actual Twin publishes `action` (a vérifier after discovery repair). | Align manifest parsing and validate actual returned fields. |
| 9antra | R3/grid authorization explicitly returns `safe_preview_tool_unconfirmed` after discovery (confirmed implementation gate; not reached in these failed discovery runs). | Agree and implement the actual Twin preview contract; re-run Water authorization. |
| Trinity / joint configuration | Shared Traffic/Air Quality carrier `SH-05` has an actuator, but its Air Quality action cap is not exposed by current action discovery. CIVIS returns `CAP_UNAVAILABLE`; no implicit unlimited allowance was added. | Publish the missing domain cap or provide reviewed static cap metadata. Clarify the meaning of null for a domain with no dedicated actuator. |
| CIVIS / partners | Water supply roles, datum and supply-preserving directions, and Power switching risk/topology remain unreviewed. | Supply the reviewed metadata and enable only the supported live policies. Geographic proximity is insufficient. |

Actual full interoperability is not green. Required acceptance assertions remain failures in the opt-in partner suite, not skipped tests or expected failures. Logs and JSON evidence remain local under `brain/.artifacts/interop-oct25/`.

The primary tagged run exercised 15 checks: 10 passed and 5 failed. Three additional legacy-security rechecks produced 1 pass and 2 failures. Together these are 18 checks, 11 passing and 7 failing, across the recorded runs. The seven failures cover discovery, three required action workflows, missing availability trust, stale rollback trust and caller-controlled signature validation. The dedicated discovery diagnostic also records the nested transport exception. `test_tagged_v3.ps1` now includes all 18 checks.
