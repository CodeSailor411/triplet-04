# CIVIS primary mock: interface development card

Status: transport scaffold only; workflows are assigned and not implemented. The complete frozen development contract is [here](docs/mock-team/CONTRACT.md). Proposed tool names/callback payloads still need partner confirmation.

- Python 3.12, FastAPI, official MCP SDK 2.3.0; protocol `2026-07-28`.
- MCP Streamable HTTP: `http://<brain-host>:8001/mcp`; health: `GET /health`.
- Every workflow call requires `Authorization: Bearer <caller-layer-key>`; Twin, Guardian and scenario keys are separate. Health/capability discovery is open.
- `get_capabilities` reports negotiated protocol, caller identity, readiness and implemented/planned tools. No key is returned.
- Planned: `evaluate_tick(batch)`, `get_active_incidents(run_id)`, `explain_decision(decision_id)`, `notify_containment(notice)` (Guardian only). They currently return `NOT_IMPLEMENTED`.
- Input readings follow current Twin's run/tick/time/reading/node/device/sensor/channel/value/unit batch. Domains come from node discovery; missing values remain null.
- Brain generates validated proposals and asks Guardian for exact-action approval before requesting Twin execution. It never isolates, quarantines, releases or rolls back devices itself.
- Current Twin wire action is a string with separate `params`; dispatch carriers are `targets` and the location is `params.destination`. Endpoint/schema adapters remain configurable.
- Missing token, unsupported required preview, unusable evidence, malformed AI output and cap refusal never permit an action. Scores alone are not tokens.
- Mock fixtures provide repeatable no-network tests; real Gemini and partner connectivity are separate smoke checks. Logs redact tokens and keys.

Known gaps and questions for partners: [PARTNER_GAPS.md](docs/mock-team/PARTNER_GAPS.md). Handover target: 9 October 2026, before 10 October.
