# CIVIS Test Book

## Execution labels

Each test has exactly one execution mode:

- `stand-in`: executed with mocks, fixtures, or simulated services.
- `real`: executed with the participating live layers.
- `not run`: not yet executed, or the required evidence is unavailable.

A test may be marked `PASS (real)` only when merged logs contain every required real-layer event under the same run ID.

## T1 - Calm city

**Execution mode:** `not run`

**Purpose:** Verify that a calm city does not cause unnecessary Brain or Twin actions.

**Prerequisites:** The calm-city scenario and agreed inputs are available. Brain and Twin event logs can be inspected, and a run ID can be identified.

**Trigger:** Execute the calm-city scenario using the agreed input.

**Expected result:** No Brain action and no Twin action occur.

**Evidence required:** Scenario input, run ID, Brain log showing no action, and Twin log showing no action.

**Pass/fail rule:**

- **PASS:** No Brain action or Twin action is recorded.
- **FAIL:** Any Brain action or Twin action is recorded.

## T2 - Real traffic jam

**Execution mode:** `not run`

**Purpose:** Verify the complete approved traffic-jam workflow across the participating layers.

**Prerequisites:** Real Twin, Guardian, and Brain services are available. The scenario and required authorization are configured. Merged logs can correlate events by the same run ID.

**Trigger:** Execute the real traffic-jam scenario.

**Expected result:** Twin records the reading, Guardian records approval, Brain records the action request, and Twin records exactly one commit. All events use the same run ID.

**Evidence required:** Twin reading event, Guardian approval event, Brain action-request event, Twin commit event, and shared run ID/event correlation.

**Pass/fail rule:**

- **PASS (REAL):** All four events are present under the same run ID, with exactly one Twin commit.
- **FAIL:** An event is missing, approval is absent, the action request is incorrect, or the Twin commit count is not one.
- **NOT PROVEN:** Evidence uses only stand-ins or does not establish a shared real run ID.

## T3 - Fake traffic jam

**Execution mode:** `not run`

**Purpose:** Verify that a fake traffic-jam reading is rejected and cannot cause a Twin action.

**Prerequisites:** The agreed fake-reading input is available. Guardian, Brain, and Twin outcomes can be inspected and correlated by run ID.

**Trigger:** Submit the agreed fake traffic-jam reading.

**Expected result:** Guardian rejects the reading, Brain blocks the action, and Twin executes nothing.

**Evidence required:** Fake-reading event, Guardian rejection event, Brain blocked-action event, Twin log showing no execution, and run ID.

**Pass/fail rule:**

- **PASS:** Guardian rejects the reading, Brain blocks the action, and Twin executes nothing.
- **FAIL:** Guardian accepts the fake reading, Brain allows the action, or Twin executes an action.

## T4 - Guardian silent

**Execution mode:** `not run`

**Purpose:** Verify safe behavior when Guardian does not respond.

**Prerequisites:** Guardian silence or non-response can be reproduced. Brain peer-failure or blocked outcomes and Twin execution events can be inspected.

**Trigger:** Execute the agreed workflow while Guardian remains silent.

**Expected result:** Brain records a peer failure or blocked outcome, and Twin executes nothing.

**Evidence required:** Guardian non-response or timeout evidence, Brain peer-failure/blocked event, Twin log showing no execution, and run ID.

**Pass/fail rule:**

- **PASS:** Brain records the peer failure or blocked outcome and Twin executes nothing.
- **FAIL:** Brain proceeds without the required Guardian response or Twin executes an action.

## T5 - Token replay

**Execution mode:** `not run`

**Purpose:** Verify that a token cannot be reused successfully for a second commit.

**Prerequisites:** A valid token and authorized first request are available. The token can be submitted again, and Twin commit and rejection events can be inspected.

**Trigger:** Submit the first request using the token, then submit a second request using the same token.

**Expected result:** The first request commits. Twin rejects the second use of the token.

**Evidence required:** First request and commit events, second request showing token reuse, Twin rejection event, and run ID/token correlation.

**Pass/fail rule:**

- **PASS:** The first request commits and Twin rejects the second token use.
- **FAIL:** The first request does not commit as expected or the replay is accepted.

## T6 - Stuck sensor isolation

**Execution mode:** `not run`

**Purpose:** Verify that a stuck sensor is isolated and the expected containment and invalidation behavior is recorded.

**Prerequisites:** Stuck-sensor input is available and Twin containment events can be inspected. Brain invalidation notification can also be inspected when real Guardian and Brain services are used.

**Trigger:** Execute the agreed stuck-sensor isolation scenario.

**Expected result:** Twin records containment. With real Guardian and Brain services, the expected Brain invalidation notification is also present.

**Evidence required:** Stuck-sensor input/event, Twin containment event, Brain invalidation notification when real Guardian/Brain services are used, and run ID/event correlation.

**Pass/fail rule:**

- **PASS:** Twin records containment; for a real Guardian/Brain execution, the required Brain invalidation notification is also present.
- **FAIL:** Expected containment is absent, or the required Brain invalidation notification is absent in a real Guardian/Brain execution.

## T7 - Duplicate command

**Execution mode:** `not run`

**Purpose:** Verify idempotent handling of duplicate commands.

**Prerequisites:** A valid command and idempotency key are available. The same key can be reused for a duplicate request, and Twin effects and responses can be inspected.

**Trigger:** Submit the original command, then submit the duplicate command with the same idempotency key.

**Expected result:** Twin produces one effect only. The duplicate request receives the original response through replay.

**Evidence required:** Original command and idempotency key, duplicate command using the same key, Twin effect record/count, original and replayed responses, and run ID/correlation information.

**Pass/fail rule:**

- **PASS:** The same idempotency key produces one Twin effect and the original response is replayed.
- **FAIL:** A second Twin effect occurs or the original response is not replayed as expected.

## Execution summary

| Test | Scenario | Execution mode | Result | Run ID | Evidence |
| --- | --- | --- | --- | --- | --- |
| T1 | Calm city | `not run` | Pending |  |  |
| T2 | Real traffic jam | `not run` | Pending |  |  |
| T3 | Fake traffic jam | `not run` | Pending |  |  |
| T4 | Guardian silent | `not run` | Pending |  |  |
| T5 | Token replay | `not run` | Pending |  |  |
| T6 | Stuck sensor isolation | `not run` | Pending |  |  |
| T7 | Duplicate command | `not run` | Pending |  |  |
