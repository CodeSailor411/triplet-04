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
- Synthetic topology: `valve-01` for `tank-01`; parameter `position_pct` (0-100), value 30, are fixture-only.
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

## Dependencies and questions for Elyes

- Valve parameter: my fixtures use `position_pct` (0-100); the synthetic S02 in tests/integration uses `position` (0-1). Which will Dali's real interface use?
- Preview and commit tool names (`fixture_preview`, `fixture_commit`) are fixture assumptions.
- `safe_valve_choices` shape (`incident_node_id`, `targets`, `params`) is my choice; please confirm it fits CONTRACT.
- Do you want a `channel` check in the detector?
- Does the core deduplicate the same incident ID re-emitted each tick while water stays high?

## PR and next action

Draft PR URL: not opened. `git push` returned 403 (account mariem-chaouachi has no write access to CodeSailor411/triplet-04). Work is committed locally.
Unit-ready status: yes
Integration-ready status: yes with fixture peers
Next step: get write access from Elyes, or use a fork or patch file, then open the PR into `codex/civis-elyes`.
