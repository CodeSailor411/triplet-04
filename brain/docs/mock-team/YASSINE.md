# Yassine: S01 persistent traffic congestion

Branch: `codex/civis-yassine`. PR base: `codex/civis-elyes`. Reviewer: Elyes, `CodeSailor411`.

You own one complete scenario: its candidate detector, constrained response, local fixtures and tests. You do not build a separate Brain server. The five release scenarios are the selected planning subset; the October checkpoint's eight incident rows are a broader catalog.

## Your exact files

- `src/civis_brain/scenarios/traffic/service.py`: `TrafficScenario`, plus helper modules inside this package.
- `tests/scenarios/traffic/test_detection.py`, `test_planning.py`, `test_workflow.py` and `helpers.py`.
- `mocks/cases/traffic/manifest.json`, `base_case.json` and `refusal_case.json`; additional variants stay here.
- `config/scenarios/traffic.json`: explicit mock policy only.
- `docs/mock-team/progress/yassine.md`.

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

Confirm the branch is `codex/civis-yassine`. In VS Code select `brain/.venv/Scripts/python.exe`. No Gemini key is required for your fixtures. Explain `Reading`, `Incident`, `Plan` and `Decision` in your own words before coding. Keep the terminal in `brain/` until Step 6.

Copy this prompt:

```text
I am Yassine on branch codex/civis-yassine, implementing S01 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, YASSINE.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/traffic/, brain/tests/scenarios/traffic/, brain/mocks/cases/traffic/, brain/config/scenarios/traffic.json and brain/docs/mock-team/progress/yassine.md. Preserve TrafficScenario.scenario_id="S01", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. For this step, inspect only and make no code changes. Confirm my branch and Windows interpreter, run the common checks, list the stubs and dependencies, and explain input, output and what my scenario is forbidden to do. Green bootstrap checks mean setup works, not that my scenario is implemented.
```

## Step 2: write the two scenario fixtures

Base evidence: Two distinct consecutive ticks with the explicit mock congestion_index threshold. Keep node/domain membership and source reading IDs.

Use shared wire models and SCENARIOS.md's fixture conventions. Case keys are `scenario_id`, `fixture_only`, `assumptions`, `nodes`, `actions`, `batches`, `policy`, `guardian`, `preview`, `ai_plan`, `twin_outcome` and `expected`. Give each fixture a scenario ID, a clear assumption list, nodes/actions/readings, recorded typed AI output when applicable, configured peer replies and expected decisions/call counts. Case files contain no keys or token strings. Shared fake Guardian generates test-only tokens in memory.

- **Base case:** A supported signal carrier, two consecutive usable congestion readings, an allowed signal plan, Guardian exact-action approval and one successful Twin response.
- **Refusal case:** The same congestion but missing exact-action token or an unsupported congestion_index feed. Record blocked/unsupported behavior and zero actuation.

Keep a small fake `PlanProvider` and fixture-reading helpers in your own `tests/scenarios/traffic/helpers.py`. Reuse Elyes's peer fixtures; do not implement another transport or shared fake peer.

Copy this prompt:

```text
I am Yassine on branch codex/civis-yassine, implementing S01 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, YASSINE.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/traffic/, brain/tests/scenarios/traffic/, brain/mocks/cases/traffic/, brain/config/scenarios/traffic.json and brain/docs/mock-team/progress/yassine.md. Preserve TrafficScenario.scenario_id="S01", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. Work only on my domain's manifest/base/refusal JSON, config and local test helpers. Write the base and refusal cases exactly as specified in my task card, with explicit synthetic assumptions and expected call counts. Validate JSON and shared model compatibility. Do not invent a fixture harness schema, partner tool, token format or safety threshold if CONTRACT leaves it unresolved; record that precise dependency in my progress file for Elyes. No scenario implementation yet.
```

## Step 3: implement the candidate detector

1. Read the threshold and persistence count from config/scenarios/traffic.json. They are illustrative mock values, not agreed traffic safety limits.
2. Recognize only congestion_index with the configured unit. The current Twin may not expose this metric yet. Do not convert speed or vehicle counts into it.
3. Require two distinct consecutive ticks. Replaying a tick does not advance a streak. Reset the supplied scenario state when the run changes.
4. Create a stable congestion candidate with its actual node IDs, domains and evidence references. No accident, injury or emergency inference.

Shared normalization runs first. Your detector still checks its sensor/unit/channel and ignores unusable/null values. A candidate is not a Guardian-approved fact. No AI or peer calls occur during detection.

Run focused tests from `brain/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/scenarios/traffic/test_detection.py -q
```

Copy this prompt:

```text
I am Yassine on branch codex/civis-yassine, implementing S01 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, YASSINE.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/traffic/, brain/tests/scenarios/traffic/, brain/mocks/cases/traffic/, brain/config/scenarios/traffic.json and brain/docs/mock-team/progress/yassine.md. Preserve TrafficScenario.scenario_id="S01", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. Implement only TrafficScenario.detect and domain-local helpers/tests using my supplied config and fixtures. Follow the detector requirements in Step 3, preserve source IDs and stable incident identity, and make no network, AI, approval or actuation call. Add meaningful tests for the normal input, applicable incident candidate, null/wrong units, duplicate ticks and run changes. If shared normalization/state handling is unavailable, report the dependency instead of changing the shared interface. Explain each helper briefly and run the focused detection tests.
```

## Step 4: implement the constrained response

1. For a supported congestion candidate, restrict the planning context to advertised set_signal_plan choices and supported traffic carriers.
2. Call only await provider.generate(context), once for this supported actionable case. Do not import Gemini, create an API client or call Twin/Guardian.
3. Return a typed Plan with R1 signal proposals using manifest parameters and existing evidence. Empty/unsupported input must produce no action.
4. Reject fabricated evidence, unknown carriers/action parameters and containment instructions. Shared core performs the final authoritative checks.

The shared core restricts the manifest and performs final evidence/action/target/parameter/risk validation. It obtains the exact-action token and requests Twin execution. Your module proposes; it cannot approve itself.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/scenarios/traffic/test_planning.py -q
```

Copy this prompt:

```text
I am Yassine on branch codex/civis-yassine, implementing S01 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, YASSINE.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/traffic/, brain/tests/scenarios/traffic/, brain/mocks/cases/traffic/, brain/config/scenarios/traffic.json and brain/docs/mock-team/progress/yassine.md. Preserve TrafficScenario.scenario_id="S01", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. Implement only async TrafficScenario.draft_plan(context,provider) and domain-local planning tests. Use await provider.generate(context) at most once for a supported actionable candidate; use a fake provider in every test. Follow Step 4's response limits, return shared Plan types, and forbid unknown actions/evidence and containment. Do not import google-genai, read secrets, call peers, generate tokens or relax preview/approval. Empty or unsupported context must produce no action. Run the focused planning tests and explain the input/output.
```

## Step 5: prove success and refusal through the shared core

Required variants: normal baseline; first elevated tick; second elevated tick; duplicate tick; changed run; null; wrong unit; unavailable metric; unknown evidence/action; missing approval; one supported success.

Add a workflow test using `from civis_brain.integration.runtime import build_runtime`. Construct it with `build_runtime(twin=fake_twin, guardian=fake_guardian, provider=fake_provider, policies=policies, features=features, artifact_dir=tmp_path)`, then call `await runtime.evaluate_tick(batch)`. Reuse the shared peer fixtures and feature schema specified in CONTRACT/SCENARIOS. Assert the final decision and exact peer call/effect counts, not just that no exception occurred. Prove both the applicable supported success and refusal case. Do not treat fixture preview/approval as evidence of live partner support.

If the core or harness is still unimplemented, record the missing function in your progress file. Keep the PR draft and label unit-complete/integration-pending when appropriate. Do not skip tests, catch `NotImplementedError` as a successful scenario, or replace workflow assertions with mocks of the entire function under test. Elyes may review/merge a unit-complete draft to enable integration; final release still needs real workflow proof.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/scenarios/traffic/ -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
```

Copy this prompt:

```text
I am Yassine on branch codex/civis-yassine, implementing S01 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, YASSINE.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/traffic/, brain/tests/scenarios/traffic/, brain/mocks/cases/traffic/, brain/config/scenarios/traffic.json and brain/docs/mock-team/progress/yassine.md. Preserve TrafficScenario.scenario_id="S01", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. Add tests only under my scenario test paths, reusing the exact shared core/harness contracts. Prove my base case and refusal case with recorded provider output and fake peers, including final decision, evidence and exact actuation/effect counts. Add the Step 5 edge variants. No live API/key or network in tests. If shared core is incomplete, record the precise blocking dependency and leave integration status pending; never skip acceptance or weaken assertions to claim success. Run focused tests, all tests and Ruff, then update my progress with actual outputs.
```

## Step 6: inspect changes and open your PR

From `brain/`, return to the repository root. Stage only your assigned paths:

```powershell
cd ..
git status --short
git add brain/src/civis_brain/scenarios/traffic/ brain/tests/scenarios/traffic/ brain/mocks/cases/traffic/ brain/config/scenarios/traffic.json brain/docs/mock-team/progress/yassine.md
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "Implement S01 traffic mock scenario"
git push origin codex/civis-yassine
```

Run the commit/push only after reviewing the staged diff and tests. In GitHub open a PR with **base `codex/civis-elyes`**, compare `codex/civis-yassine`, and request Elyes. Include implemented functions, assumptions, actual test results, base/refusal trace and remaining dependencies. Keep a draft if integration is pending. Do not force push or resolve a shared-file conflict blindly.

Copy this prompt:

```text
I am Yassine on branch codex/civis-yassine, implementing S01 only. Read brain/AGENTS.md, brain/docs/mock-team/CONTRACT.md, YASSINE.md and PARTNER_GAPS.md. My editable paths are brain/src/civis_brain/scenarios/traffic/, brain/tests/scenarios/traffic/, brain/mocks/cases/traffic/, brain/config/scenarios/traffic.json and brain/docs/mock-team/progress/yassine.md. Preserve TrafficScenario.scenario_id="S01", detect(batch,nodes,policy,state)->DetectionResult and async draft_plan(context,provider)->Plan. Do not edit shared models, registry, Gemini adapter, fake peers, dependencies or other scenarios. Review my diff and tests before committing. Confirm only my five allowed path groups changed, detect accidental secrets and missing assertions, and report defects before fixing only my files. Prepare a concise PR description with function changes, fixture assumptions, test commands/results and integration dependencies. Stage only the exact Step 6 paths. Do not claim unsupported live integration or approve/merge my PR. Target codex/civis-elyes and request CodeSailor411.
```

## Deadlines

- **8 October, 12:00 UTC+1:** small draft PR with fixtures, one function and its meaningful test.
- **8 October, 20:00:** detector/response unit work ready for review; record integration dependencies.
- **9 October, 12:00:** Elyes has merged reviewed scenario work and shared core.
- **9 October, 18:00:** your success/refusal workflows and applicable acceptance checks pass.
- **9 October, 20:00:** release candidate delivered before 10 October.
