# Member PR and leader review procedure

## Member workflow

1. Start from your assigned branch. Never edit another member's folder or the shared contract.
2. Work on one function/test at a time. Run your module tests, then all tests and Ruff.
3. Check `git diff` and `git status`. Stage only your paths with `git add <assigned-paths>`, not every file blindly.
4. Use a short technical commit message, such as `Add consecutive-tick congestion detection`. Do not paste a chat command or API key into a commit message.
5. Push your own branch. In GitHub, create a PR with **base `codex/civis-elyes`** and your branch as compare. Mark draft while incomplete; request CodeSailor411 when ready.
6. PR body: implemented functions, sample input/output, test command/results, known gaps. Include no credentials. Do not merge your own PR.

## Updating after another merge

Run Git commands from the repository root. If the terminal is currently in `brain/`, run `cd ..` first. After tests pass, stage your files with the exact member command:

| Member | Stage command |
| --- | --- |
| Yassine | `git add brain/src/civis_brain/inputs brain/config/detection-mock.json brain/tests/inputs brain/docs/mock-team/progress/yassine.md` |
| Meriem | `git add brain/src/civis_brain/planning brain/tests/planning brain/docs/mock-team/progress/meriem.md` |
| Maram | `git add brain/mocks brain/tests/workflows brain/docs/mock-team/progress/maram.md` |

Then `git diff --cached`, `git commit -m "Add completed module and its tests"`, and `git push`. Use a more specific technical message where possible. Your upstream branch is already configured by the first checkout, so `git push` targets your member branch. In GitHub the PR base dropdown must still be `codex/civis-elyes`.

Commit your work first. With a clean working tree:

```powershell
git fetch origin
git merge origin/codex/civis-elyes
```

Then re-run tests and push. Do not use force push, hard reset, or accept every conflict automatically. If a conflict appears, stop and let Elyes inspect it with you. Each branch owns separate paths, so shared-file changes should normally come from Elyes only.

## Elyes's review checklist

- The diff contains only assigned files and no environment/key/generated artifact.
- Imports, function signatures, return models and failure behavior match CONTRACT.md.
- Tests include expected values and no unwanted side effects, not just happy-path execution.
- The member explains their function and one failed case in plain language.
- No invented partner tool/parameter name, hardcoded global cap, score range or physical inference.
- The AI planner cannot call an actuator or issue a token. Brain requests; Guardian approves; Twin executes.
- Required CI checks pass on the latest integration base and conversations are resolved.
- Approve only the latest ready PR; merge serially; run all checks after the merge.

Use **Approve** in the Files changed review menu, then merge. If changes are needed, use **Request changes** and give a precise file/test request. A new commit dismisses the old approval under the integration rule.

## Final release to the triplet

After M01-M18 and the smoke checks pass, Maram opens a PR from `codex/civis-elyes` to `brain`. Elyes reviews it as CODEOWNER. This keeps the PR author separate from its reviewer. Do not send three unfinished member branches directly to other teams.

The integration branch requires one code-owner approval and successful bootstrap/file-ownership checks. Strict status checks require updating from the integration branch after it moves. Admin bypass remains available to Elyes for leader maintenance; member PRs still follow the review process. The `brain` layer's existing ownership rule remains in place.

GitHub CODEOWNERS: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners
