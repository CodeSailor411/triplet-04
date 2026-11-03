# Partner integration gaps

Current update, 26 October 2026: see [joint acceptance and partner corrections](JOINT_ACCEPTANCE_2026-10-26.md) and the [current interface](../../INTERFACE.md). Guardian v3 has named verdict/authorization tools and Twin mock3 has congestion_index and preview. The dated notes below are historical; do not report them as new failures against current tags.

Updated 11 October 2026 from the 9 October meeting and actual Twin main at 9170ee2. Local five-scenario tests pass; full partner readiness remains false. See [review evidence](INTEGRATION_REVIEW_2026-10-11.md).

| Item | Verified state | Next action |
| --- | --- | --- |
| Guardian | Real 9antra service was unavailable; tests used explicit stand-ins | Houssem supplies endpoint/key, assessment and approval tools/schemas, score scale/cut-offs, token mode and errors. Confirm simulated time in the approval request and freeze mapping. |
| Traffic metric | Twin publishes cars/min and km/h, no congestion_index | Dali and CIVIS agree a percent metric or detector conversion. Brain currently warns and does not invent congestion from speed/count. |
| Water preview | Twin marks valve preview required but has no preview tool | Obtain a preview interface. Keep live R3 blocked; do not make a silent exception. |
| Dispatch | destination was chosen in the meeting; targets are carriers | Implemented and tested against actual Twin using a test Guardian. Real Guardian approval remains unverified. |
| Token clock | Meeting agrees 60 simulated seconds; Twin uses RFC3339 iat/exp and normalized score | Implemented locally. Confirm signature mode and actual Guardian claims. Fixture score floors are illustrative; meeting floors remain placeholders. |
| Two-step actions | Brain supports advertised pending/commit. Inspected Twin has no commit_action tool despite meeting wording | Confirm availability/date and pending deadline. No unsupported call or premature success. |
| Timing and retries | Current AI timeout 60 real seconds, peer timeout 5 seconds; distinct-tick trust attempts are bounded | Agree architecture numbers, neighbour-first sequence and total deadline. Ten-second reaction compliance is not proven. |
| Cap discovery | Action manifests expose domain caps; shared targets require every touched domain's cap | Publish complete agreed limits. Missing caps block. Brain never implements Guardian's containment pools. |
| Containment | Brain polls get_containment_state and accepts Guardian-only notices | Confirm real callback wiring. Release permits fresh evidence; old corrected/quarantined evidence stays invalid. |
| Shared logs | Meeting envelope implemented; current Twin merger accepts Brain files | Agree any new event-type timeline lanes and how partner files are collected per run. |
| Human escalation | Meeting mentions it; user explicitly excluded it from this mock | Resolve scope with the team. Current implementation has no human-review workflow. |
| Future domains/GPS | Telecom/Waste and GPS conventions are later work | Unknown added fields do not break parsing; no new scenario or distance calculation was invented. |

Brain never calls Guardian-only containment/release/rollback tools. Power remains alert-only and Water needs supplied safe topology. Approved policy and real evidence are required before fixture thresholds can be used with live peers.
