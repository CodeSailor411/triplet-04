# Contributing

Each team changes only its own assigned layer folder. Root files, contracts, scenarios, logs, docs, and mockups are shared; coordinate changes with the triplet leader and affected teams.

Create a branch such as `team/civis/short-task`, `team/9antra/short-task`, or `team/trinity/short-task`. Commit focused changes, open a pull request, and request review from the assigned layer owners. Shared interfaces need agreement from all affected teams before merging.

Do not commit passwords, tokens, personal data, or real sensor identifiers. Use synthetic fixtures. Save curated scenario logs after checking their contents. Never push directly to main after protections are enabled.

CODEOWNERS requests reviews; it does not prevent local edits or restrict commits by folder. Required code-owner reviews and branch rules provide the merge gate. Until real handles and repository rules are configured, folder ownership is a working agreement only.

Before proposing a change, run `python scripts/check_setup.py`, your layer tests, and affected integration scenarios. State what is still mocked in the pull request.
