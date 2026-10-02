# City Brain Convergence â€” Civis, 9antra & Trinity

Shared Phase 1 repository for the triplet. Trinity owns Twin, Civis owns City Brain, and 9antra owns Guardian. Triplet number is awaiting confirmation; rename the remote to `triplet-XX` before submission.

## Start here

1. Read `CONTRIBUTING.md` and `docs/team-roster.md`.
2. Work in your assigned folder: Trinity → `twin/`, Civis → `brain/`, 9antra → `guardian/`.
3. Install Python 3.11+ and run `python scripts/check_setup.py` to check the repository setup.
4. Run `python scenarios/run.py scaffold-smoke` for a clearly labelled fixture demonstration and saved timeline log.
5. Run a layer's mock smoke check with `python twin/src/main.py` (or `brain` / `guardian`).

These commands test the scaffold and fixtures. Production services, a live timeline screen, authentication, and a one-command full-system startup still need implementation after the triplet agrees its architecture. No application stack has been imposed.

## Layout

- `twin/`, `brain/`, `guardian/`: independent team areas, interface cards, source, partner mocks, and tests.
- `mockups/`: design experiments; `mockups/testing/` stores usability plans and results.
- `contracts/`: proposed shared JSON messages and examples, pending team approval.
- `scenarios/`, `logs/`: one-command triggers and saved run evidence.
- `docs/`: roster, coordination evidence, architecture decisions, diagrams, report and pitch preparation.
- `.github/`: ownership setup, pull request and issue templates, scaffold checks.

## Dates from the supplied brief

Submission: 7 November 2026. Jury review: 9â€“13 November. CSTAM: 14 November, with a 2-minute pitch and 8-minute demo. Verify any organizer updates before submitting.

## Remote setup

Private remote: https://github.com/CodeSailor411/city-brain-convergence

Clone: `git clone https://github.com/CodeSailor411/city-brain-convergence.git`

See `docs/remote-setup.md`. Invite all teammates with write access, complete CODEOWNERS, and configure required reviews before treating ownership as enforced.
