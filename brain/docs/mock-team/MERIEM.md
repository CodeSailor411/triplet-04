# Meriem: S02 high-water/flood candidate

Branch: `codex/civis-meriem`. PR base: `codex/civis-elyes`. Reviewer: Elyes, `CodeSailor411`.

You own one complete scenario: its candidate detector, constrained response, local fixtures and tests. You do not build a separate Brain server. The five release scenarios are the selected planning subset; the October checkpoint's eight incident rows are a broader catalog.

## Your exact files

- `src/civis_brain/scenarios/water/service.py`: `WaterScenario`, plus helper modules inside this package.
- `tests/scenarios/water/test_detection.py`, `test_planning.py`, `test_workflow.py` and `helpers.py`.
- `mocks/cases/water/manifest.json`, `base_case.json` and `refusal_case.json`; additional variants stay here.
- `config/scenarios/water.json`: explicit mock policy only.
- `docs/mock-team/progress/meriem.md`.

Paths above are relative to `brain/`. Elyes owns shared normalization, state routing, registry, Gemini, fake peers, approval and execution. Only your scenario receives your state dictionary. Use the fixed signatures in CONTRACT and the shared Pydantic models.

## Step 1: inspect and set up on Windows

First clone/select your branch as described in SETUP. Run these from the repository root:

```powershell
git branch --show-current
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
```

Confirm the branch is `codex/civis-meriem`. In VS Code select `brain/.venv/Scripts/python.exe`. No Gemini key is required for your fixtures. Explain `Reading`, `Incident`, `Plan` and `Decision` in your own words before coding. Keep the terminal in `brain/` until Step 6.

Copy this prompt:

```text
I am Meriem on branch codex/civis-meriem, implementing S02 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, MERIEM.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/water/, brain/tests/scenarios/water/, brain/mocks/cases/water/, brain/config/scenarios/water.json and brain/docs/mock-team/progress/meriem.md. Preserve WaterScenario.scenario_id="S02", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. For this step, inspect only and make no code changes. Confirm my branch and Windows interpreter, run the common checks, list the stubs and dependencies, and explain input, output and what my scenario is forbidden to do. Green bootstrap checks mean setup works, not that my scenario is implemented.
```

## Step 2: write the two scenario fixtures

Base evidence: Persistent water_level readings using an explicit fixture-only threshold. Water level alone does not prove a leak or a safe valve change.

Use shared wire models and SCENARIOS.md's fixture conventions. Case keys are `scenario_id`, `fixture_only`, `assumptions`, `nodes`, `actions`, `batches`, `policy`, `guardian`, `preview`, `ai_plan`, `twin_outcome` and `expected`. Give each fixture a scenario ID, a clear assumption list, nodes/actions/readings, recorded typed AI output when applicable, configured peer replies and expected decisions/call counts. Case files contain no keys or token strings. Shared fake Guardian generates test-only tokens in memory.

- **Base case:** An explicit synthetic valve topology and allowed valve choice, high-water evidence, a safe fixture preview, exact-action Guardian approval and one successful Twin response.
- **Refusal case:** The same water candidate but missing or unsafe required preview. Expect blocked, no actuate call and a recorded reason.

Keep a small fake `PlanProvider` and fixture-reading helpers in your own `tests/scenarios/water/helpers.py`. Reuse Elyes's peer fixtures; do not implement another transport or shared fake peer.

Copy this prompt:

```text
I am Meriem on branch codex/civis-meriem, implementing S02 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, MERIEM.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/water/, brain/tests/scenarios/water/, brain/mocks/cases/water/, brain/config/scenarios/water.json and brain/docs/mock-team/progress/meriem.md. Preserve WaterScenario.scenario_id="S02", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. Work only on my domain's manifest/base/refusal JSON, config and local test helpers. Write the base and refusal cases exactly as specified in my task card, with explicit synthetic assumptions and expected call counts. Validate JSON and shared model compatibility. Do not invent a fixture harness schema, partner tool, token format or safety threshold if CONTRACT leaves it unresolved; record that precise dependency in my progress file for Elyes. No scenario implementation yet.
```

## Step 3: implement the candidate detector

1. Read the high-water threshold and persistence from config/scenarios/water.json. Label them mock-only; do not introduce a real hydraulic safety threshold.
2. Recognize water_level in the declared unit and require the configured consecutive distinct ticks. Preserve null and do not infer leaks.
3. Produce a flood/high-water candidate with stable ID, location and actual evidence references. Do not implement the deferred low-water scenario.
4. Keep state inside the provided per-water/run dictionary. Duplicate ticks do not increase persistence and a new run resets the history.

Shared normalization runs first. Your detector still checks its sensor/unit/channel and ignores unusable/null values. A candidate is not a Guardian-approved fact. No AI or peer calls occur during detection.

Run focused tests from `brain/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/scenarios/water/test_detection.py -q
```

Copy this prompt:

```text
I am Meriem on branch codex/civis-meriem, implementing S02 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, MERIEM.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/water/, brain/tests/scenarios/water/, brain/mocks/cases/water/, brain/config/scenarios/water.json and brain/docs/mock-team/progress/meriem.md. Preserve WaterScenario.scenario_id="S02", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. Implement only WaterScenario.detect and domain-local helpers/tests using my supplied config and fixtures. Follow the detector requirements in Step 3, preserve source IDs and stable incident identity, and make no network, AI, approval or actuation call. Add meaningful tests for the normal input, applicable incident candidate, null/wrong units, duplicate ticks and run changes. If shared normalization/state handling is unavailable, report the dependency instead of changing the shared interface. Explain each helper briefly and run the focused detection tests.
```

## Step 4: implement the constrained response

1. Allow set_valve_position only when the synthetic context explicitly supplies a permitted target/parameter choice and topology assumption.
2. Call only await provider.generate(context) once for a supported actionable candidate. The shared core owns the real free-AI adapter.
3. Return a typed R3 proposal whose preview_required flag matches the manifest. A model cannot decide that a valve change is hydraulically safe.
4. Do not fabricate a preview. The core obtains/checks preview before execution; missing live preview means blocked unless partners explicitly settle that gap.
5. Keep response constraints and test fixtures inside water paths. No direct peer call, token generation, human-review workflow or guessed valve position.

The shared core restricts the manifest and performs final evidence/action/target/parameter/risk validation. It obtains the exact-action token and requests Twin execution. Your module proposes; it cannot approve itself.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/scenarios/water/test_planning.py -q
```

Copy this prompt:

```text
I am Meriem on branch codex/civis-meriem, implementing S02 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, MERIEM.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/water/, brain/tests/scenarios/water/, brain/mocks/cases/water/, brain/config/scenarios/water.json and brain/docs/mock-team/progress/meriem.md. Preserve WaterScenario.scenario_id="S02", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. Implement only async WaterScenario.draft_plan(context,provider) and domain-local planning tests. Use await provider.generate(context) at most once for a supported actionable candidate; use a fake provider in every test. Follow Step 4's response limits, return shared Plan types, and forbid unknown actions/evidence and containment. Do not import google-genai, read secrets, call peers, generate tokens or relax preview/approval. Empty or unsupported context must produce no action. Run the focused planning tests and explain the input/output.
```

## Step 5: prove success and refusal through the shared core

Required variants: normal water; sustained high water; duplicate tick; run reset; null/wrong unit; unsupported valve target; fabricated evidence; safe fixture preview success; missing/unsafe preview refusal; missing exact approval.

Add a workflow test using `from civis_brain.integration.runtime import build_runtime`. Construct it with `build_runtime(twin=fake_twin, guardian=fake_guardian, provider=fake_provider, policies=policies, features=features, artifact_dir=tmp_path)`, then call `await runtime.evaluate_tick(batch)`. Reuse the shared peer fixtures and feature schema specified in CONTRACT/SCENARIOS. Assert the final decision and exact peer call/effect counts, not just that no exception occurred. Prove both the applicable supported success and refusal case. Do not treat fixture preview/approval as evidence of live partner support.

If the core or harness is still unimplemented, record the missing function in your progress file. Keep the PR draft and label unit-complete/integration-pending when appropriate. Do not skip tests, catch `NotImplementedError` as a successful scenario, or replace workflow assertions with mocks of the entire function under test. Elyes may review/merge a unit-complete draft to enable integration; final release still needs real workflow proof.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/scenarios/water/ -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
```

Copy this prompt:

```text
I am Meriem on branch codex/civis-meriem, implementing S02 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, MERIEM.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/water/, brain/tests/scenarios/water/, brain/mocks/cases/water/, brain/config/scenarios/water.json and brain/docs/mock-team/progress/meriem.md. Preserve WaterScenario.scenario_id="S02", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. Add tests only under my scenario test paths, reusing the exact shared core/harness contracts. Prove my base case and refusal case with recorded provider output and fake peers, including final decision, evidence and exact actuation/effect counts. Add the Step 5 edge variants. No live API/key or network in tests. If shared core is incomplete, record the precise blocking dependency and leave integration status pending; never skip acceptance or weaken assertions to claim success. Run focused tests, all tests and Ruff, then update my progress with actual outputs.
```

## Step 6: inspect changes and open your PR

From `brain/`, return to the repository root. Stage only your assigned paths:

```powershell
cd ..
git status --short
git add brain/src/civis_brain/scenarios/water/ brain/tests/scenarios/water/ brain/mocks/cases/water/ brain/config/scenarios/water.json brain/docs/mock-team/progress/meriem.md
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "Implement S02 water mock scenario"
git push origin codex/civis-meriem
```

Run the commit/push only after reviewing the staged diff and tests. In GitHub open a PR with **base `codex/civis-elyes`**, compare `codex/civis-meriem`, and request Elyes. Include implemented functions, assumptions, actual test results, base/refusal trace and remaining dependencies. Keep a draft if integration is pending. Do not force push or resolve a shared-file conflict blindly.

Copy this prompt:

```text
I am Meriem on branch codex/civis-meriem, implementing S02 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, MERIEM.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/water/, brain/tests/scenarios/water/, brain/mocks/cases/water/, brain/config/scenarios/water.json and brain/docs/mock-team/progress/meriem.md. Preserve WaterScenario.scenario_id="S02", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. Review my diff and tests before committing. Confirm only my five allowed path groups changed, detect accidental secrets and missing assertions, and report defects before fixing only my files. Prepare a concise PR description with function changes, fixture assumptions, test commands/results and integration dependencies. Stage only the exact Step 6 paths. Do not claim unsupported live integration or approve/merge my PR. Target codex/civis-elyes and request CodeSailor411.
```

## Deadlines

- **8 October, 12:00 UTC+1:** small draft PR with fixtures, one function and its meaningful test.
- **8 October, 20:00:** detector/response unit work ready for review; record integration dependencies.
- **9 October, 12:00:** Elyes has merged reviewed scenario work and shared core.
- **9 October, 18:00:** your success/refusal workflows and applicable acceptance checks pass.
- **9 October, 20:00:** release candidate delivered before 10 October.
