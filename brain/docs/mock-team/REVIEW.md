# Windows member PR and Elyes review procedure

Each member edits only their assigned scenario source, config, fixture data, tests and progress file. Elyes maintains shared infrastructure. Check scripts/ownership.json; CI reads that policy from the integration base, not the member's proposed edit.

## Run before committing

In PowerShell from brain/:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
~~~

Initial setup has only preparation checks. Add meaningful scenario tests before claiming scenario completion. Describe a missing shared runtime as an integration dependency; do not fake passing full workflows. The final candidate cannot skip required workflow tests.

Return to repository root with `cd ..`. Run git branch --show-current, git status --short, git diff. Confirm correct branch and absence of credentials/artifacts. Use your exact stage command:

| Member | Stage only these paths |
| --- | --- |
| Yassine | git add brain/src/civis_brain/scenarios/traffic brain/config/scenarios/traffic.json brain/mocks/cases/traffic brain/tests/scenarios/traffic brain/docs/mock-team/progress/yassine.md |
| Meriem | git add brain/src/civis_brain/scenarios/water brain/config/scenarios/water.json brain/mocks/cases/water brain/tests/scenarios/water brain/docs/mock-team/progress/meriem.md |
| Maram | git add brain/src/civis_brain/scenarios/emergency brain/config/scenarios/emergency.json brain/mocks/cases/emergency brain/tests/scenarios/emergency brain/docs/mock-team/progress/maram.md |

Inspect git diff --cached before committing. Use a concise technical message, for example Add congestion scenario detection and tests. Never copy a chat instruction into a commit message. Then git push to your own tracked branch.

## Create the PR

In GitHub: base codex/civis-elyes, compare your own branch. Keep draft until the declared scope is tested. Request CodeSailor411. Do not merge your own PR or target main/brain directly.

PR body:

~~~text
Scenario: S01 / persistent congestion
Implemented: [actual functions and case files]
Expected base/refusal outcomes: [status, action/evidence, zero effects when refused]
Validation: [Windows commands and results]
Integration: [proved through shared core, or exact remaining dependency]
Assumptions/gaps: [fixture-only choices and partner limitations]
~~~

Elyes may review and merge a clearly scoped unit-complete change while full integration remains assigned, but it must not claim release readiness. Final scenario sign-off requires the common-runtime workflow proof.

## Refresh after leader or another member merges

Commit your own work first; clean working tree required. From repo root:

~~~powershell
git fetch origin
git merge origin/codex/civis-elyes
~~~

Run tests again and push. Do not force push, hard reset or choose all conflict sides blindly. Show a real conflict to Elyes. A leader setup update reaches your clone using these same commands; it does not erase existing local commits.

## Elyes review checklist

- Assigned paths only; no keys/.env/generated artifacts, partner-layer implementation or shared-contract edits.
- Scenario ID, class/signatures, units and source evidence match CONTRACT/SCENARIOS.
- Member can explain one base case and one refusal without reading the AI's summary.
- No copied Gemini/MCP/Guardian stack or scenario-local token/actuation logic.
- R1/R2/R3 and preview come from the manifest; no invented safety scale, cap or physical inference.
- Tests assert exact output, call order/count and no unwanted effects.
- Latest Windows CI passes, integration base current and conversations resolved.
- Request precise changes where needed; approve only reviewed scope and merge serially.

Integration requires one code-owner review, CIVIS bootstrap and CIVIS file ownership checks, resolved conversations and an up-to-date base. New commits dismiss old approvals. Force pushes/deletion are disabled. Elyes retains repository-owner bypass for shared maintenance and root ownership.

## Release

After five workflows and shared acceptance checks pass, Maram opens the PR from codex/civis-elyes to brain. Elyes approves as Code Owner; GitHub authors cannot approve their own PR. Keep member daily commits on their own branches. Other triplet teams receive one tested integration commit, not four unfinished branches.
