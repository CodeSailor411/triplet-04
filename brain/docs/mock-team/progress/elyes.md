# Elyes progress

Updated 9 October 2026. Branch: codex/civis-elyes.

| Work | Status | Evidence |
| --- | --- | --- |
| Windows environment | Verified | Python 3.12.13; all 55 applicable package pins match; common pins match inspected Twin requirements |
| S03 Power | Complete for reduced mock | Threshold/uncertainty tests; base/refusal runs through the actual runtime |
| S04 Air Quality | Complete for reduced mock | Persistence/null/unit/run tests; base/refusal runs through the actual runtime |
| Shared core and peers | Implemented | Trust, exact token, preview, parameters, caps, idempotency, pending and containment tests |
| Direct Gemini | Live verified | Flash-Lite JSON Plan; approved demo committed one simulated effect; Guardian refusal produced zero effects |
| Debug console | Browser verified | Editable standard readings; actual request/response trace and export; desktop/mobile; no JavaScript errors or horizontal overflow |
| MCP/auth/read views | Implemented | Actual local HTTP/MCP smoke and SDK schema/refusal tests |
| Release readiness | Incomplete | S01/S02/S05 and live Guardian/preview/caps/log agreements pending |

Local verification: 104 tests, Ruff and the local MCP transport smoke passed. All 55 applicable locked packages match and the environment dependency check found no conflicts. Four offline S03/S04 presets passed. The shared action demo passed with recorded plans and live Gemini; changing its high reading to a baseline value produced zero AI calls and zero effects. Real SDK tests verify that HTTP 429/503 are not retried. CI uses no real keys or partner endpoints.

OpenRouter has been removed. Gemini configuration stays in ignored brain/.env; no credentials appear in the inspected request/response traces. See [debugging instructions](../DEBUGGING.md) and [handover](../HANDOVER.md).

Main, partner branches and member-owned scenario implementations were not changed. The synthetic action detector does not replace the member-owned S01. Fixture thresholds, cut-offs, unsigned approvals and synthetic candidates do not establish live partner integration.

Next: review member PRs sequentially into this branch, confirm partner contracts and finish the five-row acceptance matrix before release into brain.
