# Maram: fake peers, recorded AI responses and workflow proof

Branch: `codex/civis-maram`. PR base: `codex/civis-elyes`. Reviewer: Elyes.

## Your exact files

- `brain/mocks/` (Python fake peers, JSON cases and fixture AI outputs)
- `brain/tests/workflows/`
- `brain/docs/mock-team/progress/maram.md`

You may read every module, but do not change detector/planner/integration code or shared schemas. If an acceptance test fails because another module is incomplete, record the failure and ask Elyes to route the fix. Do not weaken the assertion to make it green.

## Deliverables

Complete the three stub classes in `mocks/civis_mock_peers/peers.py`: `FixtureTwin`, `FixtureGuardian`, `FixturePlanProvider`. Preserve `async call_tool(name, arguments) -> dict` and `async generate(context) -> Plan`. Constructors may take a case dictionary and record calls.

Put case data under `mocks/cases/`. Build fake peers as plain Python objects injected through the shared ports. You do not need to build two additional HTTP servers or a city simulator. Elyes supplies the live MCP adapters. Fixtures must never call the real Twin, Guardian or Gemini API.

## Implement in this order

1. Create a fixture loader and cases with declared mock data: node topology, action manifest, two consecutive reading batches when needed, simulated clock, numeric trust response, recorded AI `Plan`, configured peer refusal/commit results, and expected decision status/calls.
2. Implement FixtureTwin's `get_capabilities`, `list_nodes`, `get_readings`, `get_clock`, `list_actions`, and `actuate`. Match current Twin field names and record every invocation. Unknown tools fail clearly.
3. Make `actuate` require a token bound to action, sorted targets and normalized params; reject wrong run/expiry/mismatch. Store successful answers by logical idempotency key: same request replays, changed request rejects. Refuse over-cap requests atomically. The fake does not reproduce all Twin internals; label its assumptions in case data.
4. Count action targets as distinct nodes in each applicable domain, including both memberships of a shared node. Read cap values from the case's discovered data, not the production source's fixed table. Refused actions create no simulated effects.
5. Implement FixtureGuardian using **Elyes's frozen internal tool map**. Scores are numeric; thresholds and token lifetime are explicit fixture values, not triplet defaults. Return denial for the configured bad evidence case. Issue unsigned exact-action test tokens only inside the fake Guardian. Follow the current Twin token sample/format; Brain must never mint them.
6. Implement FixturePlanProvider by returning recorded schema-valid Plan JSON for the case. This proves predictable orchestration without consuming AI quota. It does not replace Meriem's separate live API smoke test.
7. Add explicit fixture profiles for preview available/safe, preview absent/unsafe, immediate commit, and pending/commit. Preview/commit tool names must be advertised in fixture discovery and read by the adapter. Never make fixture-only support look like present live Twin support.
8. Initially test each fake class directly. After Elyes wires orchestration, inject them and run the full acceptance matrix in `tests/workflows/`. Add a one-command test runner or pytest entry that exercises all cases and leaves a JSONL trace under ignored `.artifacts/`.

## Required cases

`traffic_r1`, `medical_r2`, `water_r3_preview`, `air_alert`, `power_no_preview`, `bad_evidence`, `missing_token`, `cap_exceeded`, `shared_node_cap`, `duplicate_command`, `pending_commit`, `ai_bad_output`, `peer_timeout`, `containment_notice`.

For each case, assert exact action/targets/params where relevant, number/order of peer calls, evidence references, final status and the absence of side effects for failures. A failure case is not passed merely because the process stayed alive. See [ACCEPTANCE.md](ACCEPTANCE.md).

## Timing and dependencies

8 Oct 12:00: fixture loader and recorded AI provider in a draft PR. 8 Oct 20:00: first three fake-peer cases and fake class tests. 9 Oct 12:00: update your branch from the integration branch after Yassine/Meriem merges, then complete workflow tests with Elyes. 9 Oct 18:00: full matrix and sample trace ready.

You can create fixtures before other modules are finished. Write no global `conftest.py`; put helpers inside `tests/workflows/` to avoid interfering with teammates' tests. Include the case assumptions, test output and one redacted trace in your progress file.

## Prompt to give your AI coding assistant

> I am Maram. Read brain/docs/mock-team/CONTRACT.md, MARAM.md and ACCEPTANCE.md. Implement only brain/mocks/, tests/workflows/, and my progress file. Use injected fake peers and recorded Plan JSON with no network/API key. Match current Twin action/params/token shapes, simulate precise refusals, record calls, and assert that failure cases have no effects. Start with fixture loading and one happy path, then add the listed failure cases. Do not implement detectors, AI API calls, orchestration or shared schemas. If another member's code is incomplete, keep the meaningful test and report the dependency to Elyes instead of silently skipping it or changing their files.
