# Integration update, 11 October 2026

S05 is integrated and corrected locally on codex/civis-elyes. See [individual review and test evidence](../INTEGRATION_REVIEW_2026-10-11.md). All five modules now pass the shared workflow checks. No remote upload or final partner approval has been made.

The earlier progress record below describes the submitted branch before this integration and is superseded where it refers to missing shared code, fixtures or scenario delivery.

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

## S08 Step 2: reported-fire fixtures only

- [x] Read the merged shared contract, models, dispatch planner and current emergency availability logic before creating fixtures.
- [x] Added six fixture-only S08 cases and a separate S08 fixture inventory; existing S05 fixtures, S05 manifest, tests and scenario code are unchanged.
- [x] Validated fixture-shaped nodes, actions, batches and plans through the shared Pydantic models; checked report source IDs and carrier/destination separation.
- [x] No `FireScenario`, detector, planner, shared runtime, provider, peer or live integration code was written. No case includes a key, token or real partner call.

The shared `Reading` model confirms the generic `run_id`, `reading_id`, `tick`, `timestamp`, `node_id`, `device_id`, `sensor`, `channel`, `value` and `unit` fields. Shared documentation names a reported-fire incident and generic R2 dispatch, with carriers as targets and the incident location as `params.destination`. It does not define a reported-fire event schema or the exact advertised firefighter unit value. S08 fixtures use conspicuous `PROVISIONAL_*` sentinels for those unknowns; these are not proposed partner values. The positive examples also keep carrier and destination identifiers distinct, and retain the report reading ID and location node.

## S08 dependencies for Elyes

- **Reported-fire event fields:** unresolved. No exact fire-report sensor/event name, channel, event value/unit, or report-to-location/source-reference mapping was found in the merged shared model, scenario code or current mock contract. The S08 report fields are marked `PROVISIONAL_*` and must be replaced only from confirmed interface evidence.
- **Exact firefighter unit type:** unresolved. Shared dispatch uses a `unit_type` choice parameter, but current code only validates `"ambulance"` for S05. The S08 advertised choice is the explicit `PROVISIONAL_FIREFIGHTER_UNIT_TYPE` sentinel, not a guess.
- **Shared dispatch helper:** unresolved for S08. Existing shared dispatch/planning checks are specific to the `"medical"` incident and ambulance; they do not validate a reported-fire incident or firefighter dispatch. Confirm the shared helper contract before implementation.
- **Current availability checks:** unresolved for firefighters. Existing S05 checks `units_free`, `channel="ambulance"`, `unit="units"`, a whole non-negative current-tick value, and retained source evidence. No equivalent firefighter channel/unit validation is confirmed; S08 availability channels are provisional.
- **Optional ambulance or police evidence:** unresolved. No confirmed injury evidence schema or fire-linked ambulance/police availability and dispatch mapping is present. The separate-injury fixture therefore makes no secondary dispatch proposal; injury is its own reading and does not authorize an action by itself.

The S08 expected counts are fixture expectations, not exercised workflow results. They distinguish provider generation, Guardian score/approval, Twin action calls and effects; no live peer calls were made. Only the requested emergency tests and Ruff check on changed Python files are to be reported for this step.

## S08 Step 3: detector and detection tests

- [x] Added `FireScenario` in `src/civis_brain/scenarios/emergency/fire.py` with `scenario_id="S08"`; it is intentionally not registered.
- [x] Detection reads the configured provisional report sensor/channel/unit, unit type, and firefighter availability sensor/channel/unit from policy. It accepts only matching non-null report evidence on a discovered Emergency node with a usable location coordinate, and retains report identity, node/location, and availability reading references.
- [x] PM2.5 alone is ignored. Null, mismatched, coordinate-less, unknown-destination and locally marked untrusted report readings do not create incidents. Repeated report IDs deduplicate within a batch and retain a stable run/report incident ID; run changes reset detector state.
- [x] Separate injury evidence is not interpreted as a fire fact and is not added to the fire candidate's sources. `draft_plan` remains an empty Step 4 stub.
- [x] Added S08 detection coverage in `tests/scenarios/emergency/test_fire_detection.py`; no S05 code or tests changed.
- [x] Final requested checks: `.\.venv\Scripts\python.exe -m pytest tests/scenarios/emergency -q` — **32 passed** (the pre-existing S05 coverage remains 20 tests); `.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts` — passed.

## S08 dependencies still open for Elyes

- **Reviewed fire-report contract:** still absent. Confirm exact report sensor/event, channel, unit/value semantics, event identity and report-to-location/source mapping. `IncidentKind="fire"` and the October report's broad mention of reported type/location/transcript do not define those fields. The string `channel="fire"` found in shared integration tests is a negative mutation against S05 medical input, not a fire contract.
- **Location mapping and coordinates:** the fixture detector uses the report `Reading.node_id` as destination and requires coordinates on that reading or its discovered node. Confirm this mapping and coordinate requirement from the reviewed event contract.
- **Trust eligibility:** shared runtime removes invalid/quarantined readings before detector invocation, but no fire report source/trust mapping is defined. The local `_s08_untrusted_reading_ids` detector-state exclusion is only a defensive unit-test hook, not a shared trust contract; future integration must preserve prefiltering and add confirmed fire evidence to shared trust eligibility.
- **Step 4 blocker — shared dispatch helper:** `EmergencyScenario._dispatch_manifest_supports` validates only `unit_type="ambulance"`; shared `validate_plan` recognizes dispatch only for `kind="medical"` and rejects any `unit_type` other than `"ambulance"`. It does not currently support firefighter dispatch. Do not duplicate or work around this helper locally; Elyes must extend/freeze the shared contract before S08 planning.
- **Step 4 blocker — firefighter availability:** current emergency checks require `units_free`, `channel="ambulance"`, `unit="units"`, a whole non-negative current-tick count, and retained evidence. Runtime trust eligibility also maps `units_free` only to `channel="ambulance"`. No firefighter availability channel/check is supported yet.
- **Step 4 blocker — exact firefighter unit type:** unconfirmed. Shared docs describe dispatch generally and list firefighter units among possible generic dispatch resources, but no exact advertised manifest choice is confirmed. `PROVISIONAL_FIREFIGHTER_UNIT_TYPE` in S08 fixtures is not an accepted value; do not hardcode or plan against it.
- **Fire dispatch routing:** the shared runtime relevance map and action routing currently include only S05 medical `emergency_calls`/`dispatch`. Registration/routing is Elyes-owned. No S08 planning, helper copy, shared edit, or registry registration was made in this step.
- **Optional ambulance or police evidence:** remains unresolved. No injury schema is inferred, and the detector does not propose or infer optional dispatches.
