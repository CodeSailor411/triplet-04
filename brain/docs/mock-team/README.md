# CIVIS primary mock: five scenarios, four Windows branches

Team: Elyes (CodeSailor411), Yassine, Meriem, Maram. Handover target: **9 October 2026 at 20:00 UTC+1**, before 10 October.

## Decision and scope

Use scenario ownership for this small mock. Each beginner owns a complete, bounded scenario: sample inputs, detector, response rules, fixtures, tests and PR. Elyes owns two smaller scenario modules and the common runtime. This is easier to explain and demonstrate than making everyone wait for a detector, planner or fixture team to finish.

There is **one Brain service**, one active free AI API adapter, one Guardian approval path and one Twin connection. A scenario is a Python module inside that service, not a separate server or copied pipeline. The AI proposes; shared code validates; Guardian approves the exact request; Twin executes. Brain never performs containment. No human-review workflow is included.

The user requested five primary scenarios. The [4 October PDF](../oct05/CIVIS_4_October_2026.pdf) actually lists eight incident types, without designating a five-scenario subset. The following five are selected from that table for this reduced checkpoint. This selection is a development plan, not a claim that the PDF records approval of these exact five. Road accident, low water and fire are deferred. Existing incident enum values remain for compatibility, but are not promised as supported workflows.

| ID | Incident from the PDF | Owner | Bounded primary response |
| --- | --- | --- | --- |
| S01 | Persistent congestion | Yassine | Advertised safe signal proposal, R1 |
| S02 | Flood / high water | Meriem | Topology-supported valve proposal, R3, only with required safe preview |
| S03 | Power overload / confirmed service loss | Elyes | Alert or blocked decision until fault evidence, topology and preview are supported; no invented outage |
| S04 | Sustained air pollution | Elyes | Air-quality alert; no AQ actuator or unsupported dispatch |
| S05 | Medical emergency | Maram | Available ambulance dispatch, R2, to the reported location |

The first version uses one primary response per scenario. The PDF's conditional cross-domain responses remain documented, but extra dispatches, grid changes or signal assistance are outside this checkpoint unless separately assigned. Keep all domain memberships and relevant context; do not claim those secondary actions are implemented.

## Read these in order

1. [Windows setup](SETUP.md)
2. [Five scenario definitions and fixture format](SCENARIOS.md)
3. [Frozen internal contract](CONTRACT.md)
4. Your task card, with an AI prompt for each development step
5. [Acceptance](ACCEPTANCE.md), [PR/review procedure](REVIEW.md), [partner gaps](PARTNER_GAPS.md)

| Member | Branch | Task card |
| --- | --- | --- |
| Elyes | codex/civis-elyes | [Two scenarios and shared core](ELYES.md) |
| Yassine | codex/civis-yassine | [S01 traffic](YASSINE.md) |
| Meriem | codex/civis-meriem | [S02 water](MERIEM.md) |
| Maram | codex/civis-maram | [S05 medical](MARAM.md) |

Each member owns their scenario source folder, config, case data, tests and progress file. Only Elyes changes contracts, package pins, configured AI adapter, fake peers, normalization, registry, orchestration, auth, server, CI and shared documents. See scripts/ownership.json for the enforced path list. The previous split by detector/planner/fixtures is superseded.

PR base for member work: **codex/civis-elyes**. Elyes reviews and merges one at a time. Update your branch after each integration merge; never force push. Fixed interfaces and separate files reduce conflicts, but do not guarantee arbitrary edits will merge safely. Maram opens the final integration-to-brain PR so Elyes can approve it.

## Meeting and delivery schedule

| Time, UTC+1 | Deliverable | Owner |
| --- | --- | --- |
| 7 Oct, meeting | Accept invitations, install Windows environment, explain assigned input/output and one refusal | All |
| 7 Oct, meeting end | Confirm five-scenario selection and partner gaps; freeze fixture assumptions and interfaces | Elyes |
| 8 Oct, 12:00 | Small draft PR: base/refusal data, detector and first meaningful unit test | Each member |
| 8 Oct, 20:00 | Each scenario's detection/planning unit tests ready; shared fake peers and configured AI adapter usable | All, Elyes for core |
| 9 Oct, 12:00 | Merge reviewed scenario PRs and compose the one shared runtime | Elyes |
| 9 Oct, 18:00 | Five workflow outcomes and failure variants pass; separate real AI/partner smoke checks | All, Elyes signs off |
| 9 Oct, 20:00 | Partner handover candidate and final release PR ready | Elyes, Maram opens PR |
| 10 Oct | Partner feedback buffer | All |

Do not wait until 9 October to build the core: Elyes starts it in parallel on 7 October. Members use a tiny local fake PlanProvider for unit tests, so no live API, token or completed core is needed for initial progress. Full workflow checks depend on the common runtime; report that dependency, never hide it with skips or weakening assertions.

## Prepared now, still to be implemented

Elyes's S03/S04, shared runtime, configured AI adapter, fake peers and MCP tools are implemented. S01/S02/S05 remain assigned to their owners. OpenRouter and the local debugging console were added on 9 October. The key authenticates, but synthetic inference returned HTTP 429; live planning is pending. See HANDOVER.md and progress/elyes.md for verified support. Full-release readiness remains false.

Elyes implements one future case trigger: from brain/, `.\.venv\Scripts\python.exe scripts/run_case.py --scenario S01 --case base` (select S01-S05). That runner is assigned, not available yet.

Release requires all five scenario outcomes, meaningful refusal tests, redacted traces, one launch/trigger path, honest readiness and documented partner gaps. Live R3 water must stay blocked if required preview is unavailable. Alert-only power is a deliberate reduced mock outcome; it does not demonstrate live grid switching. The full eight-row incident table remains the broader roadmap.
