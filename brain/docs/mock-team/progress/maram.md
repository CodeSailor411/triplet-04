# Maram progress: S05 medical emergency

Branch: `codex/civis-maram`. Scenario: `S05`. Status: unit-complete, integration-pending.
Owner paths: scenario `emergency/`, its tests/cases/config and this progress file.

## Steps

- [x] Windows setup and shared contract understood
- [x] Base/refusal fixtures validated
- [x] Detector and meaningful unit tests
- [x] Constrained response and planning tests
- [ ] Shared-core success/refusal workflow proof
- [ ] Diff reviewed, PR opened and Elyes requested

## Functions implemented

- `EmergencyScenario.detect`: records configured emergency-call and ambulance-availability observations; creates a medical candidate only for usable emergency-channel readings at/above the configured fixture threshold; preserves call and valid carrier-availability reading IDs; tracks distinct consecutive event ticks per run and returns stable incident IDs. No AI/peer/approval/actuation calls.
- `EmergencyScenario.draft_plan`: returns an empty plan without provider calls for unsupported/non-actionable contexts; for an evidence-backed medical incident with a manifest-supported carrier and available ambulance, calls the injected provider once and retains only R2 one-ambulance dispatch proposals matching the carrier, destination, manifest, preview flag, and supplied evidence. No peer/approval/token/preview/actuation calls.

## Fixture assumptions

- Synthetic nodes `EMG-INCIDENT-01` and `EMG-CARRIER-01`; carrier advertises `dispatch` and one ambulance unit.
- Fixture-only action manifest allows `dispatch`, targets the carrier, and limits unit type/destination/count to ambulance / incident node / one unit. The fixture marks preview as not required; this is not a claim about live partner support.
- The existing 1.0 calls/min event threshold is explicitly illustrative, not triplet-approved.
- Fixture Guardian approval is represented by a boolean; no token is stored or fabricated in the case files.

## Test results

2026-10-09: detector/planning units passed (18 tests); full suite passed (33 tests); `ruff check src mocks tests scripts` passed before adding the workflow cases.
2026-10-09 Step 5 run: `pytest tests/scenarios/emergency/ -q` reported 18 passed, 2 failed; `pytest -q` reported 33 passed, 2 failed; repository-wide Ruff passed. Both failures stop at `FixtureTwin(case)` with `TypeError: FixtureTwin() takes no arguments`. Unit coverage includes valid/no-candidate inputs, null/wrong channel/unit, threshold boundary, duplicate/run changes, unavailable/unadvertised ambulance, target-versus-destination, invalid type/count, and unknown evidence.
2026-10-09: S05 case JSON/Pydantic/evidence validation passed. Direct environment doctor passed. The prescribed setup script could not run because `uv` is not installed. Editor diagnostics reported no errors for the S05 detector/planning files.

## Workflow evidence

Base result and peer effect count: not observed; workflow test cannot construct `FixtureTwin(case)`. Local recorded-provider planning test accepts one evidence-bound dispatch proposal. Case expectation remains committed, one dispatch effect.
Refusal result and peer effect count: not observed; workflow test cannot construct `FixtureTwin(case)`. Case expectation is blocked after exact-action approval refusal, zero dispatch effects. Exact-action approval refusal is not established by the unit test.
Integration status: pending shared core.

## Integration blocker (S05 workflow)

- `FixtureTwin`, `FixtureGuardian`, and `FixturePlanProvider` are defined in `mocks/civis_mock_peers/peers.py` at lines 6, 11, and 16. None defines a case-taking constructor; each currently has the zero-argument `()` constructor signature.
- `tests/scenarios/emergency/test_workflow.py` constructs `FixtureTwin(case)` and `FixtureGuardian(case)`. Both workflow cases (`base_case.json` and `refusal_case.json`) fail at `test_workflow.py:62` with `TypeError: FixtureTwin() takes no arguments` before runtime evaluation.
- Needed from Elyes: a supported way to load per-case replies, including exact-action approval and Twin outcome, into the shared fake Guardian and Twin; and a supported way to inspect dispatch calls and committed effects so the base case can assert one dispatch effect and the refusal case zero.
- I did not skip, xfail, or catch this error, and did not write local fake peers. `test_workflow.py` remains the real acceptance test.
- Latest actual results: `pytest tests/scenarios/emergency/ -q`: 18 passed, 2 failed; `pytest -q`: 33 passed, 2 failed. The only failures are the two S05 workflow cases described above. `ruff check src mocks tests scripts`: passed.
- Other Elyes dependencies: confirm S05 run-identity and persistence semantics against shared state routing; confirm the manifest/expected fixture schema and Guardian preview/approval shape. The contract defines no machine-readable manifest/expected schema, so the current fixture inventory and call-count labels are provisional.

## Dependencies and questions for Elyes

- `civis_mock_peers.FixtureTwin.call_tool`, `FixtureGuardian.call_tool`, and `FixturePlanProvider.generate` still raise `NotImplementedError`; blocks replaying peer replies through the shared fixtures.
- The documented `FixtureTwin(case: dict)`, `FixtureGuardian(case: dict)`, and `FixturePlanProvider(case: dict)` constructors are absent in this checkout. The new test's first failure is `FixtureTwin(case)` raising `TypeError: FixtureTwin() takes no arguments`.
- `integration.runtime.build_runtime` and `BrainRuntime.evaluate_tick` still raise `NotImplementedError`; blocks success/refusal workflow proof.
- `inputs.normalize_batch`, `planning.service.validate_plan`, and module-level `integration.service.evaluate_tick` still raise `NotImplementedError`; shared input validation, final proposal validation, and workflow dispatch are not available.
- Guardian live tools, score scale/cut-offs, token format, and exact wire schema remain unresolved in `PARTNER_GAPS.md`. Cases use only the documented fixture `approve` boolean and do not invent score/threshold/token fields.
- Twin dispatch tool name and live manifest bounds/carrier IDs are discovery/partner-owned. Case IDs and the one-unit manifest are synthetic only.
- The docs define manifest purpose and case top-level keys but no machine-readable manifest/expected/call-count schema. `manifest.json` is a simple fixture inventory; expected call counts use documented fixture operation labels and must be mapped by Elyes before a shared loader consumes them.
- `inputs.normalize_batch` remains a shared stub, so these unit tests call the detector with typed fixture models and detector-local sensor/unit/channel checks; malformed-batch rejection is not verified here.
- `integration.runtime.build_runtime`/`evaluate_tick` remain shared stubs, so runtime state routing and end-to-end behavior are not verified. Direct detector state is kept under `_s05_*` keys and resets on run changes.
- `tests/scenarios/emergency/test_workflow.py` now exercises the frozen `build_runtime`/`evaluate_tick` API for base and exact-approval-refusal cases and asserts expected decisions, evidence, Guardian/provider/dispatch call counts, and effects. It currently fails at the missing documented peer constructor before reaching the runtime. No local orchestration substitute, skip, or `NotImplementedError` success case was added.

## PR and next action

Draft PR URL:
Unit-ready status:
Integration-ready status:
Next step and deadline: once Elyes implements the shared normalizer, plan validator, runtime, and reusable fixture peers, add the base/refusal workflow assertions with exact decision/effect counts. Keep integration pending until those assertions pass. Send the unresolved Guardian fixture and manifest/expected schema details to Elyes before a shared case loader consumes them.
