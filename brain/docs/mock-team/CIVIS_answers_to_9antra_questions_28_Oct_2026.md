# CIVIS answers to 9antra

28 October 2026. Owner: Elyes Thabet. Integration branch: `codex/civis-elyes`.

## 1–6. Twin contracts

Trinity owns these confirmations. Use its [tagged interface](https://github.com/CodeSailor411/triplet-04/blob/twin-mock-3/twin/INTERFACE.md) and Dali's response for the complete schemas. CIVIS follows the actual discovered tools. Important boundaries in `twin-mock-3`:

| Topic | Current tagged behavior |
|---|---|
| Containment names | `isolate_sensor`, `quarantine_device`, `rollback_reading`, `release_device` |
| Clock | `run_id`, integer `tick`, RFC3339 simulated UTC `time`, `tick_seconds`, `speed`, `running` |
| Preview | Brain calls `preview_action`; no `preview_id`. Twin binds the preview to caller/action/targets/params for 60 ticks. |
| Execution | Brain calls `actuate`; Guardian authorizes and contains. `commit_action` is absent and `two_step_commit:false`. |
| Feed | `/events`; MCP at `/mcp`. SSE reconnect starts at the current tick, without replay. |
| Lost action reply | Retry the identical request with the original key and token. Do not create a new operation. |
| Tokens | `iss:guardian`, `aud:twin`; one configured Guardian verification key. No tagged key-ID registry. Use one Twin worker for acceptance. |
| Ambulance evidence | `units_free`, channel `ambulance`, unit `units`, from a discovered Emergency dispatch carrier. |

`CAP_EXCEEDED`, `DEVICE_QUARANTINED` and `PREVIEW_REQUIRED` exist. `TWIN_UNAVAILABLE` and `PREVIEW_FAILED` are not public errors in this Twin tag; keep any Guardian wrapper codes explicitly separate. Do not implement against an assumed two-step or preview-ID contract.

## 7. Reading threshold

`thresholds.reading` is CIVIS's normalized minimum **evidence trust score**, dimensionless on `[0,1]`. It maps from Guardian's `guardian_verdict_policy.trusted_min_inclusive`, currently **0.7 inclusive**. It is not a sensor threshold or action permission.

## 8. Containment notification

Use the existing Brain MCP endpoint `/mcp`, tool `notify_containment`. Authenticate as Guardian with a Bearer credential matching Brain's private `BRAIN_GUARDIAN_CALLER_KEY`.

```json
{"notice":{"event_id":"containment-r1-17","run_id":"r1","state":"quarantined","device_ids":["WAT-01.water_level"],"reading_ids":["r1-w17"]}}
```

Required: `event_id`, `run_id`, `state`, `device_ids`. Optional: `reading_ids`, default `[]`. States: `isolated`, `quarantined`, `corrected`, `released`. Preserve actual Twin device and reading IDs.

| Result | Brain reply |
|---|---|
| Accepted | `{"accepted":true,"invalidated":2,"committed_effects_unchanged":true}`; count varies |
| Same event again | `{"accepted":true,"duplicate":true}` |
| Wrong run | `{"accepted":false,"code":"RUN_MISMATCH"}` |
| Missing/unknown credential | MCP error `UNAUTHENTICATED` |
| Valid non-Guardian caller | MCP error `FORBIDDEN` |

Guardian confirms the actual Twin effect first, then immediately notifies Brain. ACK confirms Brain invalidation only. It does not undo committed actions. Release permits new evidence; old invalidated IDs stay invalid.

**CIVIS delivery profile specified here:** 3 real seconds per attempt, at most one identical retry after a lost ACK. Send notices in order per device. If delivery fails, report notification pending and reconcile before declaring the workflow complete. The receiver has in-memory deduplication, no durable replay or event-order guarantee; restart requires reconciliation. Brain also checks authoritative Twin containment before acting.

The optional Guardian `BRAIN_VERDICT_URL` is a different HTTP score webhook. Do not point it at `/mcp` or treat it as this callback.

## 9. Guardian tool contract accepted by CIVIS

These names are confirmed. Maintain them in Guardian's `INTERFACE.md` and actual MCP discovery.

| Tool | Request | Reply fields used by Brain |
|---|---|---|
| `describe_capabilities` | `{}` | `protocol_version:"2026-07-28"`, `guardian_verdict_policy.trusted_min_inclusive`, `guardian_verdict_policy.risk_minimums.{R1,R2,R3}` |
| `get_trust_verdict` | `{"reading_id":"r1-w17","fresh":true}` | `trust_score`, matching `caused_by`, `scale:[0,1]`; Guardian also returns `state`, `reasons`, `cutoffs`, `history_requirement` |
| `authorize_action` | Exact command below | `decision:"approved"` plus original `token`, or `decision:"refused"` plus `refusal_code` |

```json
{"run_id":"r1","reading_ids":["r1-w17"],"action":"set_valve_position","targets":["WAT-01"],"params":{"position":40},"risk_level":"R3","domain":"Water","idempotency_key":"stable-exact-operation-key"}
```

Guardian's risk enum is `R1|R2|R3|NONE`; CIVIS actuating paths use R1–R3. Brain forwards the signed token unchanged and never signs one.

CIVIS does not send a `preview_id`: the tagged Twin supplies none. Brain obtains the existing preview before authorization; Twin enforces its cached binding when executing.

The pending verdict published in `guardian_final_version` (`f23e570`) is accepted by the CIVIS working-branch update:

```json
{"status":"pending","reading_id":"r1-w17","retry_after_ms":500,"last_scored_tick":16}
```

MCP 2.3 wraps the new union reply as `{"result":{...}}`, for both scored and pending verdicts. CIVIS unwraps that single envelope and still accepts the earlier flat reply. Brain validates identity and metadata, then retries the same original ID within the existing bounded window, at most three calls. Pending is not a score or approval. Exhaustion returns `GUARDIAN_VERDICT_NOT_READY`; malformed pending fails immediately. This support is a follow-up to the immutable `brain-mock-3` checkpoint.

**No pushed-score feed is required.** Brain and Guardian consume Twin SSE independently; Brain pulls individual fresh verdicts. A never-received reading still needs an explicit public missing-verdict error from Guardian; an opaque MCP error does not identify its cause.

## 10. Policy accepted by CIVIS for this mock

| Rule | Value |
|---|---|
| Trusted | `score >= 0.7` |
| Degraded | `0.3 < score < 0.7` |
| Untrusted | `score <= 0.3` |
| Action minima | R1 `0.50`, R2 `0.70`, R3 `0.85` |

Exactly **0.7 is Trusted** and meets the numerical R2 floor. Evidence trust and action authorization both apply, so the effective CIVIS evidence floor remains at least 0.7 even for R1.

**Keep R3 at 0.85.** A flood score of 0.75 must produce a refusal for R3. Keep that case as a negative test and use a separately justified positive case. Do not lower a safety threshold to make a fixture pass. Guardian should acknowledge these same published boundaries; this records CIVIS acceptance rather than inventing joint approval.

## 11. Joint gate and versions

From the repository root, using the current CIVIS branch:

```powershell
git fetch origin --tags
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/test_tagged_v3.ps1 `
  -IncludeBrainTests -TwinTag twin-mock-3 -GuardianTag guardian_final_version
```

Guardian source: `f23e570bf1685e155ad8ecb73cd73ef83e259fcb`. Twin source: `b012c94e4a63652c7fbe9b6baf62ce59b4a1ac9c`. Preserve these tags. For the remaining Guardian fixes, CIVIS proposes a new immutable `guardian-mock-4` tag, published and confirmed by Guardian. Do not move an already tested tag.

Logs: `brain/.artifacts/tagged-v3/<UTC-run-id>/`, including source/environment manifests, `brain.xml`, `partners.xml`, `result.json` and service evidence. Share sanitized evidence only; private signing keys are stored separately inside the run directory. `-DiagnosticsOnly` cannot certify joint acceptance. The runner is Windows PowerShell; Linux validation must be recorded separately.

## Latest verification

Final CIVIS recheck: **551 tests passed**, Ruff clean. Joint checks: **22 passed, 8 failed**, with no skips; one passing check is the test-harness regression. Evidence run: `20261027T235323826Z-f16d4f4f`, with final CIVIS results in `brain-merged.xml`.

S01 commits through actual Guardian/Twin and repeats its original request without another effect. S04's trusted alert passes; S03 passes its stated evidence-warning scope. Planning is recorded for these Windows tests; live Gemini and Linux were not retested. All 139 tagged partner source files are unchanged.

| Remaining failure group | Owner and required correction |
|---|---|
| S02, diagnostic and live | Guardian refuses R3 with `safe_preview_tool_unconfirmed`; complete its handling of the existing Twin preview contract. |
| S05 and availability control | Guardian skips `units_free`, so original availability IDs receive no verdict; support the declared resource sensor/channels. |
| Containment propagation | Guardian's local containment does not change Twin or invoke Brain's callback; implement the real calls and notification. |
| Two legacy HTTP controls | Guardian still returns cached trust after rollback and lets the caller disable signature checking. These are legacy-route findings, not proven MCP authorization bypasses. |

CIVIS corrected its pending/union adapter and a receipt-check bug in its acceptance harness. A positive unit test's artificial 150 ms wait was also changed to the existing 1.5 second budget; production timeouts were unchanged. The original run and final recheck remain separate evidence.

Use the updated `codex/civis-elyes` branch for these corrections; `brain-mock-3` is unchanged. Full three-layer acceptance remains blocked until the required failures pass.
