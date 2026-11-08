# Triplet 04 - Test Book

This Test Book verifies interactions between Trinity (Twin), 9antra (Guardian), and CIVIS (Brain). A scenario is a reproducible test case. An incident is the city condition being simulated or detected inside that scenario.

## Evidence rules

Each run has one execution label:

| Label | Meaning |
| --- | --- |
| `stand-in` | Uses fixtures, mocks, or a simulated peer. It demonstrates local behaviour only. |
| `real` | Uses the participating running layer services. |
| `not run` | Has not been executed or has insufficient evidence. |

A result may be marked `PASS (real)` only if logs from every required real layer use the same `run_id`. The logs must show the listed events. Never record a real pass from stand-in evidence.

## Scenario index

| Test ID | Name | Layers involved | Trigger | Expected result | How to verify |
| --- | --- | --- | --- | --- | --- |
| T1 | Calm city | Twin, Brain | Run the normal baseline feed | No incident or action is created | Twin and Brain logs show the same run ID and no action event |
| T2 | Approved traffic congestion | Twin, Guardian, Brain | Run a sustained congestion incident | One approved signal-control action commits | Reading, trust verdict, Brain intent, and one Twin commit share the run ID |
| T3 | Untrusted traffic reading | Twin, Guardian, Brain | Send the agreed untrusted traffic reading | Guardian refuses or marks it untrusted; Brain blocks; Twin makes no action | Guardian refusal, Brain block, and zero Twin action events share the run ID |
| T4 | Guardian unavailable | Twin, Guardian, Brain | Run an action-capable incident while Guardian does not respond | Brain fails closed and Twin makes no action | Guardian timeout or unavailable event, Brain block, and zero Twin action events |
| T5 | Approval-token replay | Twin, Guardian | Submit an authorized request, then replay the same approval token | First request commits once; replay is rejected | First commit, replay rejection, token ID and run ID in Twin and Guardian evidence |
| T6 | Stuck sensor containment | Twin, Guardian, Brain | Run the agreed stuck-sensor case | Guardian requests containment; Twin confirms it; Brain invalidates affected evidence | Containment request and effect, then Brain notification and invalidation, under one run ID |
| T7 | Duplicate command | Twin, Guardian, Brain | Send the same action request twice with the same idempotency key | One physical effect; duplicate returns the saved result | Both requests, one Twin effect, replayed response, idempotency key and run ID |
| T8 | Forged approval token | Twin, Guardian | Submit an action request with a token the Guardian never issued | Twin rejects the request and no action commits | Twin rejection, zero Twin action events, and no matching Guardian token ID under one run ID |

## Scenario specifications

### T1 - Calm city

| Field | Definition |
| --- | --- |
| ID | `T1` |
| Layers involved | Twin, Brain |
| Description | Normal readings remain within the agreed baseline. |
| Trigger | Start the calm-city feed or scenario script. |
| Expected Twin result | Streams readings and records no action. |
| Expected Brain result | Records no active incident and no action intent. |
| Pass rule | No Brain action intent and no Twin action occur for the shared `run_id`. |
| Evidence | Input/configuration, Twin log, Brain log, `run_id`. |

### T2 - Approved traffic congestion

| Field | Definition |
| --- | --- |
| ID | `T2` |
| Layers involved | Twin, Guardian, Brain |
| Description | Sustained congestion meets the agreed detector and action policy. |
| Trigger | Start the agreed traffic-congestion scenario. |
| Expected Twin result | Streams the sustained readings and commits exactly one approved signal-control action. |
| Expected Guardian result | Returns a verdict and authorizes the exact action request. |
| Expected Brain result | Detects the incident, requests authorization, and sends one matching action intent. |
| Pass rule | Reading, verdict, intent, authorization, and exactly one commit are present under the same `run_id`. |
| Evidence | Layer logs, exact action parameters, approval token ID only, idempotency key, Twin receipt. |

### T3 - Untrusted traffic reading

| Field | Definition |
| --- | --- |
| ID | `T3` |
| Layers involved | Twin, Guardian, Brain |
| Description | A deliberately untrusted traffic reading attempts to create an incident. |
| Trigger | Send the agreed untrusted reading using its fixed reading ID. |
| Expected Twin result | Records the reading and performs no signal-control action. |
| Expected Guardian result | Refuses the reading or returns an untrusted verdict. |
| Expected Brain result | Records a blocked decision and sends no action intent. |
| Pass rule | Guardian does not authorize, Brain blocks, and Twin has zero action commits for the shared `run_id`. |
| Evidence | Reading ID, Guardian verdict/refusal, Brain decision, Twin action count, `run_id`. |

### T4 - Guardian unavailable

| Field | Definition |
| --- | --- |
| ID | `T4` |
| Layers involved | Twin, Guardian, Brain |
| Description | An action-capable incident occurs while Guardian is unavailable. |
| Trigger | Run the agreed incident with Guardian stopped or configured to time out. |
| Expected Twin result | Streams readings and receives no action. |
| Expected Guardian result | No response, timeout, or declared unavailable result. |
| Expected Brain result | Records `PEER_ERROR` or a blocked decision and does not act. |
| Pass rule | Brain never bypasses missing Guardian authorization and Twin records zero commits. |
| Evidence | Guardian availability evidence, Brain peer-failure/decision event, Twin action count, `run_id`. |

### T5 - Approval-token replay

| Field | Definition |
| --- | --- |
| ID | `T5` |
| Layers involved | Twin, Guardian |
| Description | The same already-consumed approval token is submitted a second time. |
| Trigger | Submit one valid authorized action, then resubmit it with the same token. |
| Expected Twin result | Commits the first request once and rejects the replay. |
| Expected Guardian result | The original authorization remains traceable by token ID only. |
| Expected Brain result | Not involved in this scenario. |
| Pass rule | Exactly one commit occurs and the replay is rejected. |
| Evidence | First request/receipt, replay request/rejection, token ID, effect count, `run_id`. |

### T6 - Stuck sensor containment

| Field | Definition |
| --- | --- |
| ID | `T6` |
| Layers involved | Twin, Guardian, Brain |
| Description | A stuck or unreliable sensor needs containment. |
| Trigger | Run the agreed stuck-sensor scenario. |
| Expected Twin result | Applies and reports the requested isolation or quarantine if authorized. |
| Expected Guardian result | Detects the problem and sends the containment notification after Twin confirms the effect. |
| Expected Brain result | Acknowledges the notification and invalidates affected evidence or plans. |
| Pass rule | The confirmed containment effect is followed by a Brain invalidation event under the same `run_id`. |
| Evidence | Sensor ID, Guardian request, Twin containment receipt, Brain callback/acknowledgment, invalidation event, `run_id`. |

### T7 - Duplicate command

| Field | Definition |
| --- | --- |
| ID | `T7` |
| Layers involved | Twin, Guardian, Brain |
| Description | A command is repeated after a lost or delayed client reply. |
| Trigger | Send the exact same action request twice with the same idempotency key. |
| Expected Twin result | Produces one physical effect and returns the stored first response to the duplicate. |
| Expected Guardian result | No second authorization is required for a replay of the identical request. |
| Expected Brain result | Correlates the duplicate response with the original operation. |
| Pass rule | One effect is recorded and the duplicate receives the original response without a second action. |
| Evidence | Both requests, shared idempotency key, original and replayed response, Twin effect count, `run_id`. |

### T8 - Forged approval token

| Field | Definition |
| --- | --- |
| ID | `T8` |
| Layers involved | Twin, Guardian |
| Description | A request carries an approval token that the Guardian did not issue. |
| Trigger | Submit an action request with a forged token. |
| Expected Twin result | Rejects the request and performs no action. |
| Expected Guardian result | Has no record of issuing the presented token. |
| Expected Brain result | Not involved in this scenario. |
| Pass rule | The Twin rejects the forged token and records zero commits for the shared `run_id`. |
| Evidence | Forged request, Twin rejection, Twin action count, Guardian record, `run_id`. |

## Execution record

Fill this table only after a run. Link or name the saved layer logs and preserve their shared `run_id`. One row per saved log file. The run ID restarts when the Twin restarts, so the same ID can appear on different days (for example `run-42-005` on 3 Nov and 8 Nov); the evidence file identifies the run.

| Test ID | Execution label | Result | Shared run ID | Evidence location | Notes |
| --- | --- | --- | --- | --- | --- |
| T1 | `real` | PASS | run-42-002 | `logs/T1-1.jsonl` | Run on 3 Nov 2026. Calm run: the log holds only the run start and end. |
| T2 | `stand-in` | PASS | run-42-004 | `logs/T2-1.jsonl` | Run on 3 Nov 2026. Stand-in Brain and stand-in Guardian. |
| T3 | `stand-in` | PASS | run-42-005 | `logs/T3-1.jsonl` | Run on 3 Nov 2026. Stand-in Guardian set to refuse. |
| T4 | `stand-in` | PASS | run-42-006 | `logs/T4-1.jsonl` | Run on 3 Nov 2026. Stand-in Guardian set to stay silent, so it wrote no events; the stand-in Brain logged the failure. |
| T5 | `stand-in` | PASS | run-42-007 | `logs/T5-1.jsonl` | Run on 3 Nov 2026. Stand-in Guardian; no Brain events. |
| T5 | `real` | PASS | run-42-003 | `logs/T5-2.jsonl` | Run on 8 Nov 2026. Twin and real Guardian; no Brain involved. |
| T6 | `stand-in` | Partial | run-42-008 | `logs/T6-1.jsonl` | Run on 3 Nov 2026. The script's checks passed (sensor isolated, containment logged), but there are no Brain events, so the Brain invalidation required by the pass rule is not shown. |
| T7 | `stand-in` | PASS | run-42-009 | `logs/T7-1.jsonl` | Run on 3 Nov 2026. One effect, duplicate answered with the saved result. |
| T8 | `real` | PASS | run-42-005 | `logs/T8-1.jsonl` | Run on 8 Nov 2026. Twin and real Guardian; no Brain involved. |