# CIVIS integration interaction list

20 October 2026. This is an interaction checklist with recorded test coverage, not a claim that all three production services passed.

| Interaction | Required result | Evidence/status |
| --- | --- | --- |
| Brain authenticates to Twin MCP | Correct key accepted; wrong caller refused | Existing transport/security suite; partner calls use temporary separate keys |
| Twin SSE to Brain | Readings continue during planning | Real SSE Air Quality and delayed Medical tests pass |
| Clock advances | Fresh authorization time; no exact-tick deadlock | Real running-clock Medical test passes |
| Run reset, disconnect, gap, queue overflow | In-flight plan invalidated; no false persistence | CIVIS regressions pass |
| Native Twin readings to Guardian | Schema accepted with original identity/units | Blocked: actual Guardian returns 422 |
| Guardian evidence assessment | Numeric scores bound to exact reading IDs | Contract fixture tests pass; real MCP operation missing |
| Typed planner to Brain | Validate action, units, evidence, targets and risk | Five-scenario suite; recorded planner/HTTP tests |
| Water preview | Exact command, checks pass, preview not expired | Real Twin preview and CIVIS refusal tests pass |
| Guardian exact-action approval | Original token, exact intent, current simulated lifetime | Test Guardian passes; actual issuer missing |
| Twin actuation | One committed effect, atomic refusal | Real Water/Medical controls pass; denial and containment prevent effects |
| Recurring versus persistent incident | New episode gets new key; retry retains key | Traffic, Water and Medical regression tests pass |
| Lost send or wrong receipt | Unconfirmed, bounded same-request reconciliation | CIVIS regressions pass |
| Pending confirmation | Immediate, original key, bounded retry/deadline | Contract tests pass; real Twin tool missing |
| Guardian containment and Brain callback | Invalidate affected evidence; no Brain containment privilege | Local callback and real Twin containment checks pass; Guardian outbound path missing |
| Expired token/new cleared reading | Block before action | CIVIS regressions pass |
| Shared logs | Reading IDs, token ID, operation key; no secrets | Log tests plus sanitized partner run artifacts |

Next joint acceptance requires real Guardian assessment/approval/containment, the Traffic metric, reviewed Water policy, and an agreed recovery sequence. Two-step stays disabled until Twin exposes its interface and joint tests pass.
