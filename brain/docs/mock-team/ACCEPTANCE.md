# Acceptance: five scenarios plus shared checks

Elyes approves release evidence. Each owner proves their own full scenario through the common runtime; unit tests alone are not partner handover. Current tests verify preparation only.

| ID | Owner | Base outcome | Required refusal/edge proof |
| --- | --- | --- | --- |
| S01 persistent congestion | Yassine | R1 advertised signal request commits exactly once with correct evidence | One tick/null/duplicate tick does not create persistence; denied/missing approval produces zero actuation |
| S02 flood/high water | Meriem | Declared safe topology/preview fixture permits exact R3 valve request | Missing/unsafe preview or unsupported target blocks; no assumed valve direction; zero actuation |
| S03 power overload/service loss | Elyes | Explicit saved alert/blocked result when confirmed fault/preview/topology is unavailable | Low load alone never asserts outage; no grid operation; unsupported-evidence warning appears in decisions/trace |
| S04 sustained air pollution | Elyes | Alert with source readings and no AQ actuator | No uncorroborated emergency dispatch; missing/wrong-unit/single-tick evidence does not trigger sustained incident |
| S05 medical emergency | Maram | R2 dispatch with ambulance carrier, separate destination and supported available unit | No available units, wrong carrier/destination or denied approval means no dispatch; no inferred injury facts |

Power/AQ successful demonstration means correct alert/blocked handling and zero physical effects. Water's positive path is explicitly fixture-only until live preview support is confirmed. Keep base and refusal variations under these same five IDs. Accident, low water and fire are not required scenario workflows in this checkpoint.

## Shared checks, owned by Elyes

| Check | Evidence required |
| --- | --- |
| Input/auth | Reject wrong required fields, mismatched run/tick/count, unknown nodes and unauthenticated callers; ignore unknown extra fields; preserve null |
| Evidence/approval | Untrusted data, numeric score only, absent/mismatched/expired/wrong-run token cannot authorize a successful action |
| AI failure | Invalid JSON, unknown action/evidence, extra token, quota/timeout and injected instructions become bounded failures, with zero actuator effects |
| Caps | Atomic CAP_EXCEEDED, shared-domain counting and original detail retained; no partial effects, unchanged retry or split-to-bypass |
| Idempotency | Same command acts once; modified intent cannot reuse old approval/key; uncertain network outcome keeps original key |
| Optional pending | Confirm only if advertised; absent confirmation leaves honest pending/blocked result; never log premature commit |
| Containment notice | Only Guardian caller accepted; affected evidence/queued intent invalidated; Brain never contains/releases |
| Five-module routing | Fixed registry, independent per-run scenario state, preserved shared-node domains, no unrelated action from a single-case run |
| Handover | One launch and one scenario-trigger path, honest readiness, redacted trace, exact commit/config and documented live limitations |

These are shared test assertions or variants within S01-S05, not additional primary scenarios. No live AI/peer request in automated tests. Never mark a required workflow passed merely because the server stays alive or NotImplementedError was expected.

## Release record

All tests and Ruff pass on Windows, including meaningful full workflows. Save one trace per scenario with status, reason and evidence, plus at least one blocked trace. No skipped required behavior. Record fixture assumptions and partner commit/protocol versions.

Run one separate synthetic live Gemini smoke check under free-tier access and real partner discovery/auth checks when endpoints/keys are supplied. Passing fixtures cannot be reported as completed live integration. Preview/schema gaps must be visible in the partner handover; readiness describes actual supported features.
