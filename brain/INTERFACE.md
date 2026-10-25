# Development update, 25 October 2026

Branch `codex/civis-elyes` adds optional `GUARDIAN_TRANSPORT=mcp_v3`, adapting Guardian's actual `describe_capabilities`, `get_trust_verdict` and `authorize_action` tools. Brain forwards the original Guardian `g1` token, binds its claims to the exact action/evidence/idempotency key and Twin clock, and leaves signature verification/consumption to Twin. The five public Brain MCP tools and Reading wire schema remain unchanged.

S07 low-water fixture workflows now use the shared R3 preview/authorization/execution path. S06 is detection plus explained alert; S08 is detection with its member response still pending. These new live scenarios default to disabled until report/topology policy is reviewed. The geographic graph is internal planning/debug context from existing discovery, with reference distances and no inferred infrastructure links. No new public graph API is required.

Current results, exact partner tags and remaining failures: [25 October review](docs/mock-team/PR_REVIEW_AND_V3_ACCEPTANCE_2026-10-25.md). [Shared helper and handover](docs/mock-team/ELYES_SHARED_CORE_2026-10-25.md). Full joint action acceptance remains blocked. The published `brain-mock-2` checkpoint remains unchanged; the older release interface follows.

# CIVIS Brain mock interface

20 October 2026, brain-mock-2. Python 3.12; MCP SDK 2.3.0; protocol 2026-07-28. Partners run `scripts/start_partner.ps1` with the private `.env.partner`; see [handover](docs/mock-team/BRAIN_MOCK_2.md). MCP: http://127.0.0.1:8001/mcp. Developer console: http://127.0.0.1:8001/. Dependencies remain pinned in requirements-lock.txt.

| Tool | Arguments | Caller/result |
| --- | --- | --- |
| get_capabilities | {} | Public discovery; full joint readiness is false |
| evaluate_tick | {batch} | Twin, Guardian or scenario caller; DecisionBatch |
| get_active_incidents | {run_id} | Authenticated caller; active candidates |
| explain_decision | {decision_id} | Authenticated caller; saved result, no re-execution |
| notify_containment | {notice} | Guardian only; evidence invalidation |

Separate inbound Bearer keys: BRAIN_TWIN_CALLER_KEY, BRAIN_GUARDIAN_CALLER_KEY, BRAIN_SCENARIO_KEY. Outbound keys: TWIN_BRAIN_KEY and GUARDIAN_BRAIN_KEY. Keep secrets in ignored .env; development defaults are not partner credentials. Brain never issues a Guardian approval or calls Twin containment tools.

## Input and workflow

Batch: run_id, tick, time (simulated UTC RFC3339), tick_seconds, count, readings. Reading: run_id, reading_id, tick, timestamp, node_id, device_id, sensor, channel, value, unit, optional lat/lon (finite WGS84 degrees). Null remains null. Node discovery supplies all domain memberships. Future domains and unknown extra fields do not break the existing five scenarios. Traffic accepts percent and %, preserving the original unit.

With PEER_MODE=live and TWIN_FEED_ENABLED=true, Brain reads authenticated Twin /events independently while one worker evaluates batches. An external driver may still call evaluate_tick; choose one driver per run. Hello/heartbeat time is wall time and never authorizes an action. /health includes feed state, counters and last error. Debug presets remain isolated synthetic replays, not a claim about the live partner run.

Flow: discovery and containment -> normalization -> detection -> Guardian evidence scores -> typed Gemini plan -> local validation -> required preview -> exact-action Guardian token -> fresh clock/containment check -> Twin actuate. Scores never replace tokens. There is no mock-approval fallback in live mode.

## Clocks, gaps and execution

- Peer call: 3 real seconds by default. Gemini: at most 60 real seconds, before authorization.
- Batch and Twin must agree on run, tick rate and elapsed simulated time. Evidence may be at most MAX_EVIDENCE_AGE_SECONDS old at execution: 10 simulated seconds by default, 60 in the explicit partner mock profile for Gemini latency. This is a configurable CIVIS mock safeguard, not a newly agreed triplet value. Slow plans can be refused.
- Approval uses a fresh Twin clock. Token validity is checked again before sending; maximum token lifetime is 60 simulated seconds.
- Reception and planning use separate tasks with a bounded 64-batch queue. Gaps, reconnects, overflow and run changes invalidate queued plans. Missing ticks never establish consecutive evidence. Newer feed data can withdraw a cleared incident or unavailable ambulance.
- preview_action receives only action, targets and params. Brain checks the returned exact intent, would_pass_checks, blocked_by and valid_until_tick. A successful dry run means caps/quarantine checks pass, not hydraulic safety. Water additionally requires configured safe_valve_choices. Reduced Power is alert-only; no grid-switch plan is generated.
- An operation key binds run, scenario, incident episode and normalized command. Persistent incidents reuse receipts. A confirmed clear followed by a new incident gets a new key; missing data or a gap does not clear an episode.
- Lost-send reconciliation makes at most one repeat using the original in-memory token, request and key after fresh checks. Unresolved overlapping actuator operations are blocked. Receipts for a different request are not treated as success.
- If a configured confirmation tool is advertised, Brain confirms pending immediately with the original key. Budget: 10 real seconds from send, at most two 3-second calls and one 1-second wait after transport uncertainty. Deadline is not extended. Current Twin does not advertise commit_action, so joint confirmation is unverified.

## Five scenarios and configuration

| Scenario | Reduced response | Current partner boundary |
| --- | --- | --- |
| S01 Traffic | R1 signal plan | Twin supplies vehicle_count (cars/min) and avg_speed (km/h); CIVIS expects congestion_index (%). Agree and test a native-metric policy or explicit conversion |
| S02 Water | R3 valve, topology and preview required | Preview works; safe valve direction must be explicitly supplied |
| S03 Power | Alert or evidence warning | No invented outage or grid switching |
| S04 Air Quality | Sustained-pollution alert | No AQ actuator |
| S05 Medical | R2 ambulance dispatch | Requires current availability and exact approval |

MOCK_INTEGRATION_PROFILE=true explicitly permits illustrative policies against partner mocks. It defaults to false. SCENARIO_POLICY_FILE optionally loads local overrides keyed by S01-S05, including reviewed Water choices; use an ignored path such as .artifacts/local-policies.json. It does not bypass trust, preview or caps. Source configuration remains test policy, not physical safety settings.

Guardian's MCP endpoint exposes RF advisory tools. Tagged v2 also provides HTTP ingestion, evaluations and an incompatible signed-action contract; see the HTTP option below. Keep the selected evidence mapping explicitly configured, and never interpret mapping confirmation as full action acceptance. The [Guardian adapter contract](docs/mock-team/GUARDIAN_CONTRACT.md) describes the internal fields. Live recovery gathers matching advertised neighbours, waits at most 3 real seconds for later readings of the same sensors, then requests a fresh verdict over original and supporting evidence. Total budget is 10 real seconds. No substituted readings or synthetic scores grant trust. A failed recovery exhausts that incident's budget. Pushed Guardian verdicts remain outside this mock; assessment uses the selected existing transport.

Live mode reuses the original confirmed receipt for a completed episode without another Gemini call. A new clear-then-incident episode can act again. Changing policy or restarting requires a new Twin run.

Logs: run-logs/<run_id>.brain.jsonl with run_id, event_id, timestamp, tick, wall, layer, event_type, caused_by, data. Approval records include token ID, never the full token. Decisions include the operation key. State is in memory: use a new Twin run after restarting Brain, and reconcile uncertain outcomes first. Logs do not restore execution state.

See the [release handover](docs/mock-team/BRAIN_MOCK_2.md) and [validation](docs/mock-team/RELEASE_VALIDATION.md) for scope, commands and partner blockers.
## Tagged Guardian v2 HTTP option, 23 October 2026

Set `GUARDIAN_TRANSPORT=http_v2`, `GUARDIAN_HTTP_URL` and `GUARDIAN_HTTP_POLICY_FILE` to the partner's explicit published policy JSON. `GUARDIAN_BRAIN_KEY` is Guardian's incoming API Bearer key, distinct from Twin caller keys. Guardian's separate feed bridge must ingest actual Twin data; Brain does not re-ingest or synthesize readings.

This internal adapter reads existing `/health` and `/api/evaluations?limit=200` endpoints. It binds verdicts to original content and preserves rejections. `guardian_http_scores` and `guardian_http_approval` are internal port operation names, not new MCP tools or public endpoints. Existing Guardian MCP mode remains unchanged. An explicit HTTP evidence-mapping confirmation does not certify action-token compatibility.

Current tagged Guardian approvals use an incompatible `g1` format without exact Twin targets and use wall time. This adapter therefore refuses physical actions with `GUARDIAN_TOKEN_CONTRACT_UNSUPPORTED`; it never translates or re-signs a token. Missing evidence, bounded-window expiry and run changes are also explicit blockers. Preflight remains unready. See `docs/mock-team/INTEROPERABILITY_2026-10-23.md` for reproduction and partner fixes.
