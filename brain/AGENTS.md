# CIVIS five-scenario development rules

Read docs/mock-team/README.md, SCENARIOS.md, CONTRACT.md and the card matching the current branch. User instructions take precedence.

- The current plan is five scenario modules, superseding detector/planner/fixtures team ownership.
- Work only on current assigned branch and paths in scripts/ownership.json. Implement only that member's tasks, one step at a time.
- Elyes owns shared models/ports, normalization, fixed registry, single configured AI provider (OpenRouter selected; Gemini optional), fake peers, live clients, approval/execution, settings, dependencies, CI and release.
- Members own their scenario detector/response, fixtures, tests and progress. Never duplicate the common runtime or implement another member's files.
- Preserve class IDs and frozen method signatures. Report gaps to Elyes before changing shared interfaces.
- Use Windows PowerShell and brain/.venv Python 3.12 with the committed lock. Do not upgrade packages independently.
- Read PARTNER_GAPS.md. Unmerged partner code and old proposals are evidence, not new agreements.
- AI proposes typed responses only. Guardian approves exact requests; Twin executes/enforces caps. Brain never contains, releases or issues approval tokens.
- Missing evidence/approval/required safe preview means blocked, never fabricated success. Scores are not permission.
- Keep source IDs, null, units and multi-domain membership. No guessed thresholds, outage/leak facts or safe valve directions.
- Threshold examples are fixture-only. Three deferred incident types are not implemented for this checkpoint.
- Keep API/peer calls out of CI. Never expose/commit .env, keys or tokens.
- Run meaningful member tests plus full suite/Ruff. Do not skip required failures or hide an incomplete shared runtime.
- Member PRs target codex/civis-elyes, reviewed by CodeSailor411. No force push or blind conflict resolution.

- Keep the local debug page plain: light background, standard controls, tables and JSON. No decorative dashboard or frontend framework.
