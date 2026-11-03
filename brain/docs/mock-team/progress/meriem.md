# Integration update, 11 October 2026

S02 is integrated and corrected locally on codex/civis-elyes. See [individual review and test evidence](../INTEGRATION_REVIEW_2026-10-11.md). All five modules now pass the shared workflow checks. No remote upload or final partner approval has been made.

The earlier progress record below describes the submitted branch before this integration and is superseded where it refers to missing shared code, fixtures or scenario delivery.

# Meriem progress: S02 high-water / flood candidate

Branch: `codex/civis-meriem`. Scenario: `S02`.
Status: unit-complete and workflow-proven against the shared core with fixture peers; live partner integration not claimed.
Owner paths: scenario `water/`, its tests/cases/config and this progress file.

## Steps

- [x] Windows setup and shared contract understood
- [x] Base/refusal fixtures validated
- [x] Detector and meaningful unit tests
- [x] Constrained response and planning tests (including edge variants)
- [x] Shared-core success/refusal workflow proof (fixture peers)
- [ ] Diff reviewed, PR opened and Elyes requested (push blocked by 403, see below)

## Functions implemented

- `WaterScenario.detect` (via `detector.detect_high_water`): flags a flood candidate when `water_level` in cm is at or above `threshold_min` for `persistence_ticks` consecutive distinct ticks. Null and wrong-unit readings are unusable and never converted. Duplicate ticks add no persistence, a skipped tick restarts the streak, and a new run resets history. Matching `safe_valve_choices` from the policy are exposed in `Incident.facts.supported_valve_actions`. No AI or peer calls.
- `WaterScenario.draft_plan` (via `planner.plan_response`): no flood incident gives an empty plan and no provider call; no manifest-supported valve choice gives an alert only and no provider call; otherwise one provider call, and only proposals that exactly match a supported choice (action, targets, params, R3, preview flag, non-empty detector evidence IDs; the shared model also enforces at least one) are kept. The rest are dropped with an alert.

## Fixture assumptions

- Threshold 100 cm and 2 ticks are mock values from `config/scenarios/water.json`, not hydraulic safety limits.
- Synthetic topology: `valve-01` for `tank-01`; parameter `position` (0-100, unit %), value 30, are fixture-only. (Corrected 24 October: an earlier version of this note said `position_pct`.)
- `config/scenarios/water.json` has `safe_valve_choices: []` (alert only). The valve choice lives in the case files' own policy.
- Guardian score scale 100 and cut-offs follow the shared fixture shape; mock values, not Houssem-confirmed.
- Preview, Guardian approval and Twin commit answers are fixture values and do not prove live support.
- Detector checks sensor and unit only; `channel` is not checked.

## Test results

- `pytest tests/scenarios/water/ -q` -> 37 passed
- `pytest -q` -> 123 passed
- `ruff check src mocks tests scripts` -> All checks passed!

## Workflow evidence

- Base: final status committed, 1 provider call, 1 fixture_approve, 1 actuate call, 1 effect.
- Refusal (unsafe preview): final status blocked, 1 provider call, 0 actuate calls, 0 effects.
- Also proven: missing preview blocks, missing approval blocks, one high tick and normal water do nothing, and fake evidence / unsupported target / wrong param never reach Twin.
- Integration status: fixture peers only. Not live partner proof.

## Dependencies and questions for Elyes (S02)

- Valve parameter scale: my cases use `position` 0-100 (%); `tests/integration/helpers.py` uses `position` 0.0-1.0. Which will the live Twin use?
- Preview and commit tool names (`fixture_preview`, `fixture_commit`) are fixture assumptions.
- `safe_valve_choices` shape (`incident_node_id`, `targets`, `params`) is my choice; please confirm it fits CONTRACT. Elyes's own test in `test_oct19.py` uses `WAT-01` as both incident node and valve target, a different shape from my `tank-01` plus `valve-01`.
- Do you want a `channel` check in the detector?
- Answered from the code: the core gives each scenario its own state dict (`runtime.py`, `self.states`) and assigns stable episode IDs with receipts, so a repeated incident ID is not decided again each tick.

## PR and next action (S02)

Draft PR URL: not opened. `git push` returned 403 (account mariem-chaouachi has no write access to CodeSailor411/triplet-04). Work is committed locally.
Unit-ready status: yes
Integration-ready status: yes with fixture peers
Next step: get write access from Elyes, or use a fork or patch file, then open the PR into `codex/civis-elyes`.

---

# S07 low-water supply (24 October 2026)

Branch: `codex/civis-meriem`. Scenario: `S07`.
Status: detector, planner reuse, config validation and unit tests done. Fixture only, not live. S07 through the shared runtime is blocked on a shared-core change (see below).

## Why high water proves neither a leak nor a valve choice

A high `water_level` is one number at one node. It can come from a burst, but also from rain or inflow, a closed downstream valve, pump operation, sensor drift, a wrong unit or datum, or normal filling. It says the level is high, not that water is escaping. Which valve to change depends on topology and hydraulics the number does not carry: which valves are connected, flow direction, what each valve isolates, and who loses supply if it closes. So the code acts only on a configured, incident-specific valve choice, after preview and exact-action approval. With no such choice the result is alert/blocked and no valve change.

## Input tables

| Field | S02 high water | S07 low water |
|---|---|---|
| Sensor | `water_level` | `water_level` |
| Unit | cm (declared in policy, no conversion) | cm (declared in policy, no conversion) |
| Local datum | not declared today | `datum` in policy, required (fixture value: reservoir floor, unconfirmed) |
| Threshold | `threshold_min` 100.0, triggers at `>=` | `threshold_max` 30.0, triggers strictly below (`<`); equal is not low |
| Duration | `persistence_ticks` 2 consecutive distinct ticks | `persistence_ticks` 2, separate streak and separate state |
| Recovery | not defined | `recovery_level` 45.0; a usable reading at or above it re-arms; the dead band between 30 and 45 breaks the streak but does not re-arm |
| Scope | any water node | only nodes listed in `supply_nodes` (empty in shipped config, so detection is disabled) |
| Valve choice | `safe_valve_choices` in policy | separate list; a choice is exposed only if `supply_preserving` is true and `reviewed_topology_ref` is set, so an S02 choice cannot be copied across |

Policy checks: `policy_error` rejects a wrong scenario id, missing sensor, unit or datum, empty `supply_nodes`, non-finite thresholds, `recovery_level <= threshold_max`, and `persistence_ticks` outside 1 to 100. `pair_error(high, low)` rejects different units, a low threshold at or above the high threshold, and a recovery level that overlaps the high-water band.

## Steps

- [x] 1. Water tests run, explanation written (above)
- [~] 2. Input tables written; question to Elyes about real supply nodes and policy not yet answered
- [x] 3. `LowWaterScenario` implemented (own state, strictly-below logic, duplicate ticks do not extend the streak)
- [x] 4. Planner reused with incident-specific reviewed choices; missing choices give alert only, no provider call
- [ ] 5. Shared runtime enforcement of preview plus exact-action approval for S07: tested locally, needs Elyes's patch
- [ ] 6. Graph explanations and emergency assistance: not started

## Files

- `src/civis_brain/scenarios/water/low_water.py` (new)
- `src/civis_brain/scenarios/water/planner.py` (`kind` and `label` parameters; S02 behaviour and alert text unchanged)
- `config/scenarios/water_low.json` (new; `supply_nodes` empty)
- `mocks/cases/water/low_base_case.json` and `low_refusal_case.json` (new)
- `tests/scenarios/water/test_low_water.py` and `test_low_water_workflow.py` (new)

## Test results

- Committed branch: water suite 75 passed, 10 skipped; full suite 374 passed, 10 skipped; ruff clean. The 10 skipped are the S07 workflow tests, which skip until S07 is registered.
- With the shared-core patch applied locally: water suite 85 passed, 0 skipped. The only full-suite failure was `test_all_five_delivered_modules_share_one_runtime_without_cross_scenario_actions`, which hardcodes S01 to S05. The patch adds S07 to its expected set; the full suite after that edit has not been re-run.
- Workflow cases for S07: base commits one valve change; unsafe-preview refusal blocks; missing topology, missing preview, Guardian denial, expired approval, normal water and unsupported proposals never actuate.

## Blocked on shared core (Elyes)

Patch: `s07-shared-core-change.patch` (four files).

1. `registry.py`: add `LowWaterScenario()` and `"S07"`.
2. `runtime.py`: add S07 to `RELEVANCE` and `ACTION_BY_SCENARIO`. Registering S07 without this makes every scenario return `INPUT_INVALID` (113 failures in the trial).
3. `planning/service.py`: `PRIMARY_ACTIONS` ties `set_valve_position` to kind `flood`, so an S07 `low_water` incident gets `EVIDENCE_INCOMPLETE`. The patch lets that action also accept `low_water`.
4. `tests/integration/test_member_integration.py`: add `"S07"` to the expected scenario set.

## Physical assumptions (not code)

- Supply nodes, datum, valve, valve direction and the position value 80 are all synthetic (`reservoir-01`, `valve-02`).
- Thresholds 30 cm and 45 cm and 2 ticks are mock values, not hydraulic safety limits.
- A `Reading` has no datum field, so the datum is declared in policy and cannot be checked per reading.
- No live topology is available. A synthetic case is not proof of it.
- Preview, Guardian approval and Twin commit answers are fixture values.

## Missing partner inputs (not code bugs)

- Which nodes are real reservoir or supply nodes, and under which policy low water there means supply failure.
- Declared unit and local datum, and whether `Reading` should carry a datum field.
- Which valves are reviewed as supply-preserving, and in which direction.
- Live valve scale: 0 to 100 or 0 to 1.
- Which fixture shape is canonical: `WAT-01` or `tank-01` plus `valve-01`.
- Whether `uv.lock` should be committed.
- Push access (403).

## Not covered yet

- Stale-evidence test (`max_evidence_age_seconds` in the runtime features) and a wrong-datum test (needs a datum on readings, Elyes's decision).
- `PREVIEW_EXPIRED` applies only when `preview_tool` is `preview_action`; the fixtures use `fixture_preview`, so it is not exercised.
- Step 6: graph explanations for verified water connectivity only, keeping "nearby" separate from "downstream", and emergency assistance only from independent people-affected evidence through the shared core. Needs Elyes's graph and emergency code.

## PR and next action

Draft PR URL: not opened. Work is committed locally. Next step: send Elyes the patch and questions, get write access or hand over the patch, then open the PR into `codex/civis-elyes`. In the PR description, state that the topology is synthetic and that S07 through the runtime depends on the shared-core patch.