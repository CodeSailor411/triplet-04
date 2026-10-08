# Meriem progress: S02 high-water / flood candidate

Branch: `codex/civis-meriem`. Scenario: `S02`.
Status: detector and constrained response implemented (unit-complete); shared-core workflow proof pending.
Owner paths: scenario `water/`, its tests/cases/config and this progress file.

## Steps

- [x] Windows setup and shared contract understood
- [x] Base/refusal fixtures validated
- [x] Detector and meaningful unit tests
- [x] Constrained response and planning tests (including edge variants)
- [ ] Shared-core success/refusal workflow proof (blocked, see Dependencies)
- [ ] Diff reviewed, PR opened and Elyes requested

## Functions implemented

- `WaterScenario.detect` (via `detector.detect_high_water`): flags a flood candidate when `water_level` in cm is at or above `threshold_min` for `persistence_ticks` consecutive distinct ticks. Null and wrong-unit readings are unusable and never converted. Duplicate ticks add no persistence, a skipped tick restarts the streak, and a new run resets history. Matching `safe_valve_choices` from the policy are exposed in `Incident.facts.supported_valve_actions`. No AI or peer calls.
- `WaterScenario.draft_plan` (via `planner.plan_response`): no flood incident gives an empty plan and no provider call; no manifest-supported valve choice gives an alert only and no provider call; otherwise one provider call, and only proposals that exactly match a supported choice (action, targets, params, R3, preview flag, non-empty detector evidence IDs) are kept. The rest are dropped with an alert.

## Fixture assumptions

- Threshold 100 cm and 2 ticks are mock values from `config/scenarios/water.json`, not hydraulic safety limits.
- Synthetic topology: `valve-01` for `tank-01`; parameter `position_pct` (0-100), value 30, are fixture-only.
- `config/scenarios/water.json` has `safe_valve_choices: []` (alert only). The valve choice lives in the base case's own policy.
- Preview, Guardian approval and Twin commit answers are fixture values and do not prove live support.
- Detector checks sensor and unit only; `channel` is not checked (note for Elyes).

## Test results

## Test results

- `pytest tests/scenarios/water/ -q` -> 28 passed
- `pytest -q` -> 43 passed
- `ruff check src mocks tests scripts` -> All checks passed!

## Workflow evidence

Base result and peer effect count: not run (pending shared core).
Refusal result and peer effect count: not run (pending shared core).
Integration status: pending.

## Dependencies and questions for Elyes

- `mocks/civis_mock_peers/peers.py`: FixtureTwin, FixtureGuardian, FixturePlanProvider raise NotImplementedError (re-check before PR); blocks workflow tests.
- `integration.runtime.build_runtime` / `evaluate_tick`: <exists / missing>.
- Which policy does `build_runtime` use: the case-file policy or `config/scenarios/water.json`?
- Does the core deduplicate the same incident ID re-emitted each tick while water stays high?
- Valve parameter name, bounds and preview/commit/approval tool names are fixture assumptions, not partner-confirmed.
- `safe_valve_choices` shape (`incident_node_id`, `targets`, `params`) is my choice; please confirm it fits CONTRACT.

## PR and next action

Draft PR URL: (fill in after opening)
Unit-ready status: yes (detector + response)
Integration-ready status: no
Next step: open draft PR labelled unit-complete / integration-pending, then write workflow tests when the core lands. Next checkpoint: 9 October 12:00.