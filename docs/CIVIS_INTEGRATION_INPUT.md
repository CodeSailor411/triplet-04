# CIVIS input for INTEGRATION.md

**7 November 2026 status:** This draft's rows describe the earlier gate. [Current source pins, corrections and evidence](../brain/docs/mock-team/JOINT_FIX_2026-11-07.md) now show real S02/S05 commits and the Guardian containment callback. The bounded 14-check actual-service gate passes with recorded planning. Rollback and caller-disabled-signature controls from this draft were not rerun in that gate; full Test Book completion and live Gemini are not claimed.

## 1. CIVIS role
Brain handles incident detection, typed intent, evidence validation, the Guardian request and the Twin execution request.

## 2. Current flow
Twin readings and the clock go to Brain. Brain runs individual trust checks with Guardian. Brain sends the exact approved command to Twin. A Guardian containment notice invalidates Brain's evidence after a Twin effect.

## 3. What passed
- Individual-flow evidence: Actual S03 alert and S04 sustained-PM2.5 alert workflows pass with real Guardian evidence. Power alerts do not certify the unfinished switching workflow. (brain/docs/mock-team/PR_REVIEW_AND_V3_ACCEPTANCE_2026-10-25.md)
- Stand-in evidence: Actual partner integration controls passed (14 passed): real Twin MCP/SSE, advancing clock, configured app startup without fixture files and low-trust recovery. Positive actions use an explicit test Guardian, so this is not three-layer approval acceptance. (brain/docs/mock-team/RELEASE_VALIDATION.md, 20 October 2026)
- Stand-in evidence: S07 passes offline workflows; Fire shared positive/refusal paths pass with a clearly labelled test wrapper. (brain/docs/mock-team/PR_REVIEW_AND_V3_ACCEPTANCE_2026-10-25.md)
- Fixture evidence: The Water positive path is explicitly fixture-only until live preview support is confirmed. (brain/docs/mock-team/ACCEPTANCE.md)

## 4. What remains blocked
CIVIS-F01: S05 does not complete
CIVIS-F02: Guardian containment callback does not match Brain's input
CIVIS-F03: Rollback failed
CIVIS-F04: Signature enforcement incomplete
CIVIS-F05: S02 blocked in an earlier run
CIVIS-F06: No fresh three-layer joint gate has passed

## 5. Acceptance rule
All three real services must produce matching same-run evidence for the required Test Book flow. Stand-in and fixture tests do not satisfy it.
