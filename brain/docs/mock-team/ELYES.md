# Elyes: S03 Power, S04 Air Quality and the shared Brain core

Branch: `codex/civis-elyes`, the protected integration branch. You review the three member PRs. Your two alert-focused scenarios leave time for the shared integration work.

The release contains five selected scenarios. The October checkpoint's eight incident rows remain the broader catalog; the chosen five names are a planning subset, not a claim of recorded triplet approval. Accident, low water and fire are deferred.

## Your exact scope

Your own scenarios:

- `src/civis_brain/scenarios/power/service.py`: `PowerScenario`, `scenario_id="S03"`.
- `src/civis_brain/scenarios/air_quality/service.py`: `AirQualityScenario`, `scenario_id="S04"`.
- `tests/scenarios/power/`, `tests/scenarios/air_quality/`.
- `mocks/cases/power/`, `mocks/cases/air_quality/`.
- `config/scenarios/power.json`, `config/scenarios/air_quality.json`.
- `docs/mock-team/progress/elyes.md`.

Shared core: normalization, per-scenario/run state, static registry, models/ports/settings, one Gemini adapter, reusable fake peers, MCP/auth, trust/preview/action validation, execution, logs, CI and release evidence. Paths are relative to `brain/`. Leave traffic/water/emergency implementations, tests, fixtures and policies to their owners. Do not implement `twin/` or `guardian/`.

Fixed scenario signatures:

```text
scenario_id: str
detect(batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict) -> DetectionResult
async draft_plan(context: PlanningContext, provider: PlanProvider) -> Plan
```

## Step 1: Windows setup and contract freeze

From the repository root:

```powershell
git branch --show-current
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
```

Confirm `codex/civis-elyes` and select `brain/.venv/Scripts/python.exe` in VS Code. Collect member GitHub usernames and grant individual access. Confirm actual Guardian schemas/tools/keys, Twin `action` plus `params`, dispatch carrier/destination and required preview support. Record unresolved items in PARTNER_GAPS; do not guess the answers.

Only you need a local Gemini key for the shared live smoke test. Keep it in ignored `brain/.env`. Members develop with recorded provider responses; their own keys are optional if they help with the later live check.

Copy this prompt:

```text
I am Elyes on codex/civis-elyes. Read brain/AGENTS.md, mock-team CONTRACT, SCENARIOS, ELYES, ACCEPTANCE and PARTNER_GAPS. Inspect the Windows setup and run bootstrap checks without implementing business logic yet. Confirm the five scenario IDs, public MCP models, internal signatures and exact partner gaps. Explain the shared core's input/output and why numeric trust is not permission. Do not edit member-owned traffic/water/emergency files, invent Guardian contracts or expose keys.
```

## Step 2: fixture format, reusable peers and small shared foundation

1. Keep the registry explicit: S01 traffic, S02 water, S03 power, S04 air_quality, S05 emergency. No arbitrary file scanning/import plugins.
2. Normalize batch semantics once: run/tick/count/time consistency, known nodes, finite values, preserved nulls and domains joined from nodes. Unknown/null/unusable readings cannot become action evidence.
3. Give each scenario its own mutable state per run. No shared persistence counters. Repeat ticks do not advance history; a changed run resets state.
4. Implement reusable `FixtureTwin`, `FixtureGuardian` and `FixturePlanProvider` under `mocks/civis_mock_peers/`. They record calls/effects, return explicit configured responses and never use a network/key. Case JSON contains no keys or token strings; the fake Guardian generates test-only approvals in memory. Member-local helpers only load their own cases.
5. Follow SCENARIOS's case fields: `scenario_id`, `fixture_only`, `assumptions`, `nodes`, `actions`, `batches`, `policy`, `guardian`, `preview`, `ai_plan`, `twin_outcome`, `expected`.
6. Supply base/refusal cases for your Power and AQ modules. Power base is an explicitly configured mock overload candidate or independently confirmed service-loss evidence, followed by an alert. Refusal/uncertainty is low load alone or absent agreed threshold/evidence, with no grid command. AQ base is sustained mock PM2.5 elevation with an alert; refusal is null/invalid evidence or an attempted unsupported AQ action, with no actuation.
7. Freeze `build_runtime(*, twin, guardian, provider, policies, features, artifact_dir=None)` and `await runtime.evaluate_tick(batch)` for the team. Do not change them while member PRs depend on them without explicit coordination.

Copy this prompt:

```text
Implement only Elyes-owned shared normalization/state/registry and reusable fixture peers, plus S03/S04 fixture/config paths. Preserve all public MCP models and the frozen runtime factory. Use an explicit five-entry registry, separate scenario/run state, SCENARIOS case keys and call/effect recording. No real network, AI, approval or Twin effects in fixture code. Do not complete member scenario modules or edit their tests/config/cases. Add focused foundation tests and explain any unresolved field instead of inventing it.
```

## Step 3: implement your two alert-focused detectors

**S03 Power:** use an explicit mock-only overload threshold if configured. A load/voltage reading may justify a candidate warning; low load alone does not prove service loss. Classify confirmed service loss only with a separately agreed corroborating source/condition. Do not add an invented fault flag to Twin's wire model. When relevant Power readings are present, missing policy/support produces an explicit unsupported/uncertain alert. An unrelated scenario batch must not gain a Power alert.

**S04 Air Quality:** use the configured illustrative PM2.5 threshold/unit and persistence. Require distinct consecutive ticks, preserve evidence and label an air-pollution candidate. Do not infer fire, victims or a need for emergency dispatch from PM2.5 alone.

Both return `DetectionResult` using their own state. Stable incident IDs, null/wrong-unit checks and run reset apply. Detector warnings must become recorded alert/blocked decisions through the core.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/scenarios/power/test_detection.py tests/scenarios/air_quality/test_detection.py -q
```

Copy this prompt:

```text
Implement only PowerScenario.detect, AirQualityScenario.detect and their own helper/test paths. Use explicit mock policies and the Step 3 evidence rules. Do not infer outage from low load or fire from PM2.5. Preserve actual evidence IDs, nulls, stable candidate identity and per-run persistence. Keep unsupported power classification visible as a warning for a recorded core decision. No network, AI or physical action. Run focused detector tests including baseline, applicable candidate, duplicate tick, changed run, null/wrong unit and insufficient evidence.
```

## Step 4: one free-AI adapter and guarded shared execution

Your Power/AQ `draft_plan` methods return alert-only typed Plans by default. They propose no grid/AQ/dispatch action and require no provider call. Do not invent a grid risk tier or AQ actuator.

Implement the shared core in this order:

1. One `GeminiPlanProvider` using the pinned SDK, schema-constrained `Plan`, bounded context, timeout and call budget. No tools/search/paid fallback. A failed free API call becomes blocked, never random substitute success.
2. Live `ToolPeer` adapters use configured endpoints/caller keys and discovered protocol/tool schemas. Missing Guardian mappings block the joint workflow.
3. Select usable evidence through Guardian's actual checks. Use agreed numeric cut-offs only. A score/cached score is not exact-action permission.
4. Invoke each applicable scenario's constrained `draft_plan` with a restricted action manifest. Physical proposals still receive shared checks for known action, carriers, params, evidence, risk and preview.
5. Obtain required safe preview and Guardian token for the exact normalized action/targets/params under Twin's run/clock. Missing support/token blocks. Fixture preview is test-only. No human-review flow.
6. Twin alone executes. Preserve rejection details/caps, use stable command idempotency, reconcile uncertain outcomes and never split cap-refused commands to bypass limits.
7. Handle pending/commit only when advertised. Missing confirmation support leaves pending with explanation; never fabricate a commit.
8. Wire active incidents, explanation and Guardian-only containment notification. Invalidate affected queued evidence; Brain never isolates/quarantines/releases/rolls back devices.
9. Implement one shared `scripts/run_case.py` runner with `--scenario S01` through S05 and `--case base` or refusal. Load the selected domain case, create shared fixtures/runtime, evaluate its batches and write a redacted trace under ignored .artifacts/. Do not copy orchestration into five scripts. Default uses fixture AI/peers; live Gemini smoke is separate.
10. Save redacted decision/evidence traces. Readiness stays false until the completed acceptance matrix passes.

Copy this prompt:

```text
Implement Elyes's shared Gemini adapter and runtime using the frozen Scenario/PlanProvider/ToolPeer/build_runtime contracts, then Power/AQ alert-only draft_plan methods. Do not implement traffic/water/emergency modules. Follow Step 4's bounded free-API, discovery, evidence, deterministic validation, exact-action token, preview, idempotency, cap refusal and optional pending rules. No guessed Guardian names/scales/safety settings, fabricated preview or containment operation. Keep secrets out of logs/tests and readiness false until final acceptance. Work in small tested increments; report partner gaps explicitly.
```

## Step 5: shared integration proof and sequential member review

Workflow tests use:

```python
from civis_brain.integration.runtime import build_runtime

runtime = build_runtime(
    twin=fake_twin,
    guardian=fake_guardian,
    provider=fake_provider,
    policies=policies,
    features=features,
    artifact_dir=tmp_path,
)
result = await runtime.evaluate_tick(batch)
```

Use the feature schema in CONTRACT/SCENARIOS, not guessed dictionary keys.

- Review each member's own unit work and changed paths before sequential merges. A unit-complete draft can be merged after your review to unblock composition if integration-pending is recorded.
- Each scenario must ultimately prove its base and refusal behavior through the actual shared runtime. Your AQ/Power outcomes are successful alerts, not successful physical actions.
- Shared tests cover authentication/caller roles, unavailable tool/schema, bad AI output, missing/mismatched token, unsafe/missing preview, cap refusal, duplicate/changed intent, pending, containment invalidation, peer timeout and secret redaction.
- Reject false-positive testing that mocks the entire workflow, skips missing functionality or catches `NotImplementedError` as success.
- Update bootstrap health tests to reflect conditional readiness without claiming unfinished functions are implemented.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/scenarios/power/ tests/scenarios/air_quality/ tests/integration/ -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
```

Copy this prompt:

```text
Review member PR contracts and then test the real shared Brain runtime using injected recorded provider and fake peers. Add only Elyes-owned integration and S03/S04 tests. Assert final decisions, evidence, exact call/effect counts and no unwanted action for all refusals. Keep tests key/network-free. Missing core or partner schema is a recorded dependency, never skipped acceptance. Run focused tests, all tests and Ruff; review auth, token, preview, caps, idempotency, pending, containment and log redaction. Record actual outputs in elyes progress.
```

## Step 6: review, integration branch and final release

Members PR into `codex/civis-elyes`. You review their scope, test evidence, assumptions and both workflow outcomes. Merge sequentially and rerun all tests. Shared changes must be communicated before members refresh their branches. Do not edit their active scenario packages behind their branches.

For your own scenario progress commit, from `brain/`:

```powershell
cd ..
git status --short
git add brain/src/civis_brain/scenarios/power/ brain/src/civis_brain/scenarios/air_quality/ brain/tests/scenarios/power/ brain/tests/scenarios/air_quality/ brain/mocks/cases/power/ brain/mocks/cases/air_quality/ brain/config/scenarios/power.json brain/config/scenarios/air_quality.json brain/docs/mock-team/progress/elyes.md
git diff --cached --check
git diff --cached
git commit -m "Implement S03 power and S04 air quality mock scenarios"
git push origin codex/civis-elyes
```

For shared-core commits, stage explicit reviewed paths inside your ownership scope. Do not use `git add .`, include `.env`, stage another member's active work or force push. Admin maintenance bypass is available, but record local checks before pushing integration changes.

Before release, run the full acceptance matrix, one synthetic live Gemini check and actual partner discovery/auth checks. Exchange real keys privately. Handover includes commit/branch, Windows launch commands, MCP URL/protocol, example payloads, fixture assumptions and current partner gaps.

Ask **Maram to open the release PR** from `codex/civis-elyes` into `brain` under her own account, then review it yourself. GitHub authors cannot approve their own PR. Keep root/Brain CODEOWNERS assigned to you.

Copy this prompt:

```text
Review Elyes-owned staged changes and all scenario integration evidence. Check secrets, file ownership, unchanged public interfaces, Windows setup, five scenario scope and unresolved partner assumptions. Prepare a concise release description and partner launch handover. Do not create false readiness, skip acceptance or claim fixtures prove live integration. Stage only explicit Elyes-owned paths and show the diff before commit. Member PRs target codex/civis-elyes. After final checks, Maram opens the release PR into brain and Elyes reviews.
```

## Deadline and workload

- **8 October, 12:00 UTC+1:** all members have small draft PRs; shared fixture/runtime contracts are usable.
- **8 October, 20:00:** your detector/alert unit work and reviewed member unit work are ready.
- **9 October, 12:00:** reviewed scenario PRs merged and shared core composed.
- **9 October, 18:00:** all five scenario success/refusal checks, safeguards and live smoke checks complete.
- **9 October, 20:00:** release candidate handed over before 10 October.

The core is the schedule's critical dependency. If partner preview/Guardian schemas cannot be confirmed, report the blocked live pathways and fixture-only demonstrations accurately. No last-minute extra scenario, dashboard or AI framework belongs in this checkpoint.
