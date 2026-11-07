# CIVIS input for integration

## 1. CIVIS role

CIVIS Brain detects incidents, creates a typed action intent, validates the supporting evidence, requests Guardian trust and exact authorization, then requests Twin execution. Brain does not sign tokens or perform containment.

## 2. Current flow

Twin readings and the simulated clock reach Brain through the authenticated feed and MCP discovery. Brain requests a fresh Guardian verdict for each source reading, validates the exact command and required Twin preview, then requests Guardian authorization. Brain forwards the original approved token and idempotency key to Twin. After Twin confirms a containment effect, Guardian calls Brain's `notify_containment` tool so Brain invalidates the affected evidence.

## 3. What passed

* CIVIS regression suite: 555 tests passed; Ruff passed.
* Current tagged-service gate: 22 checks passed. These cover transport, discovery, refusal handling, selected Twin controls and bounded Brain behaviour.
* S01 committed once when the Twin traffic evidence remained current. A newer cleared reading correctly blocks the action with `EVIDENCE_CHANGED`.
* The agreed S03 evidence-warning path passed within its alert-only scope.
* The optional read-only traffic graph forecast and Gemini interpretation completed against the Twin feed. They do not provide action evidence, risk decisions, authorization or execution.

These results do not establish full three-layer acceptance.

## 4. What remains blocked

| ID | Status |
| --- | --- |
| CIVIS-F01 | S05 Medical remains blocked because Guardian does not produce a current trust verdict for the required native ambulance `units_free` evidence. |
| CIVIS-F02 | Guardian containment remains local and does not yet produce the confirmed Twin effect and Brain `notify_containment` callback required for the live workflow. |
| CIVIS-F03 | Guardian rollback freshness remains unresolved: the latest check retained a stale trusted score after rollback. A previous joint check also returned a rollback failure. |
| CIVIS-F04 | Guardian signature-enforcement policy remains incomplete: an authenticated caller could disable reading-signature validation in the tested legacy HTTP path. |
| CIVIS-F05 | The earlier Brain S02 harness mismatch, valve position 30 versus the agreed 40 percent, was corrected. S02 remains blocked because Guardian has not completed the R3 safe-preview prerequisite. |
| CIVIS-F06 | No fresh full three-layer Test Book gate has produced matching same-run evidence for every required service interaction. |

## 5. Acceptance rule

All three real services must produce matching evidence under one run ID for the required Test Book flow. Fixture and stand-in results are useful diagnostics but do not satisfy joint acceptance. Corrected partner builds must be tagged and the gate rerun before any blocked row is closed.
