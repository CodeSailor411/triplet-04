# GitHub setup

Created private remote: https://github.com/CodeSailor411/city-brain-convergence

Owner: CodeSailor411. Rename to `triplet-XX` once the number is confirmed. Collaborator invitations, per-team CODEOWNERS, and branch rules remain pending.

The local repository is independent from the parent workspace. Run commands from this folder.

1. Sign in: `gh auth login -h github.com`.
2. Confirm the owner (account or organization), triplet number, and members.
3. Create the private remote using the confirmed values:
   `gh repo create OWNER/triplet-XX --private --source . --remote origin --push`
4. Invite confirmed GitHub usernames through Settings > Collaborators and teams with write access. Do not share credentials.
5. Replace commented examples in `.github/CODEOWNERS` with real usernames or organization team slugs.
6. Configure a main branch rule: require pull requests, code-owner review, and the `Scaffold checks` status check; block force pushes and deletion. Availability depends on the owner/account plan.
7. Copy the actual remote URL into the root README and share it with the teams.

Teammates clone the confirmed URL, create a feature branch, and follow CONTRIBUTING.md. Never run the example with literal OWNER or XX.
