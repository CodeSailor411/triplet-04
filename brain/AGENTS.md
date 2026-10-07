# CIVIS primary mock development rules

Read docs/mock-team/README.md, CONTRACT.md, and the task card for the current member branch before coding. User instructions take precedence over this file.

- Work on the current assigned branch and only its paths in scripts/ownership.json.
- Elyes owns shared models, settings, dependency pins/lock, transport wiring, integration, CI and release. Members do not change those to accommodate generated code.
- Preserve the frozen public function signatures. Report contract gaps to Elyes before changing another member's interface.
- Implement only the member's assigned tasks. Do not finish another member's business module or claim the whole mock is ready.
- Use the brain/.venv Python 3.12 environment and committed lock. Do not upgrade packages independently.
- Read current PARTNER_GAPS.md; do not treat the old proposal or unmerged partner code as final agreement.
- The AI planner only proposes typed actions. Guardian approves exact requests; Twin executes and enforces trust/caps. Brain never performs containment.
- Missing token, evidence, required preview or supported partner schema means blocked behavior, not a fabricated successful response.
- Numeric scores are not approval. Do not invent Guardian scales, cut-offs or live safety thresholds.
- Keep live AI/peer calls out of unit/CI tests. Use fixtures. Never expose or commit .env, keys or tokens.
- Run the assigned meaningful tests, all tests and Ruff before a ready PR. Do not replace assertions with skips to hide incomplete workflows.
- Member PRs target codex/civis-elyes and require CodeSailor411 review. No force push or blind conflict resolution.
