# Local Brain debugging

From brain/, start .\.venv\Scripts\python.exe -m civis_brain and open http://127.0.0.1:8001/. Restart after changing Python code or .env.

## Explain the page

1. **Environment:** installed versions, service peer mode, selected AI model, whether a key exists, and remaining live API calls. No key value is displayed.
2. **Load and edit a request:** choose one of the five scenarios, base/refusal and Recorded response or Gemini API. The JSON contains the exact readings submitted by Run request. Reload standard readings restores the preset.
3. **Result:** the real Brain decision, refusal code, number of model calls and simulated effects. Committed means the mock Twin confirmed an effect; alert means no actuator action.
4. **Request and response trace:** expand each entry to see discovery, evidence assessment, model input/final Plan, preview when required, approval and actuation. Tokens are redacted.
5. **Download:** saves the current request and result as JSON. Custom inputs are not graded against the original preset.
6. **AI connection only:** one real Gemini request without Guardian/Twin or an effect. Usually use Run request for the complete workflow.
7. **Active service events:** the long-lived MCP runtime's events. Each debug replay is isolated, so it does not populate that service's active run.

## Five scenarios

| Scenario | Base | Refusal | AI needed |
| --- | --- | --- | --- |
| Traffic S01 | Two high percent readings, approved R1 signal, 1 effect | Guardian denies, 0 effects | Yes |
| Water S02 | Supported valve choice, safe preview, approved R3 valve, 1 effect | Unsafe preview, 0 effects | Yes |
| Power S03 | Recorded alert | Insufficient fault evidence warning | No |
| Air Quality S04 | Sustained PM2.5 alert | Unsupported evidence warning | No |
| Medical S05 | Medical call plus ambulance availability, approved R2 dispatch, 1 effect | Guardian denies, 0 effects | Yes |

All ten presets use actual scenario modules and the same shared runtime. Guardian and Twin are fake peers on this page. Recorded response uses a stored Plan and no network AI; Gemini API uses a real Gemini Plan with those same fake peers.

For a quick edit test, load Traffic base and change the second value from 95 to 20. Two consecutive high ticks are no longer present: no AI call and no effect. Preserve run/tick/time/IDs/node/sensor/unit/channel; null stays null.

Water's positive preview is a declared fixture. Actual Twin currently lacks the preview tool. Actual Twin also lacks Traffic's congestion_index metric. See [partner gaps](PARTNER_GAPS.md).

## Gemini and safety controls

Local .env uses LLM_MODE=gemini, GEMINI_MODEL=gemini-3.5-flash-lite, AI_TIMEOUT_SECONDS=60 and PEER_MODE=fixture. The key stays in ignored .env. API requests use structured JSON, store=false, bounded output and no automatic retries or search tools. Only final output is displayed.

The page shares a budget of three live calls per server session across runs and the API-only check. Restart to reset that local budget. Recorded cases are unlimited. Loopback/session/origin checks protect the console; BRAIN_DEBUG_ENABLED=false disables it.

## Evidence

On 11 October, 264 automated tests, Ruff and environment checks passed. Browser checks covered all primary presets, custom inputs and desktop/mobile layouts. One real Gemini request per S01/S02/S05 base case produced one validated Plan and simulated effect. These are not real Guardian approvals.

Ignored .artifacts/debug/review-*.json contains the inspected requests/results; .artifacts/debug/last-run.json is the latest export. [Review report](INTEGRATION_REVIEW_2026-10-11.md) records the individual corrections and MCP/actual Twin checks.
