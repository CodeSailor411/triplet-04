# CIVIS primary mock: team meeting and work plan

Owner: Elyes (CodeSailor411). Team: Elyes, Yassine, Meriem, Maram.
Target: a handover candidate on **9 October 2026 at 20:00**, before 10 October. Times below are UTC+1.

## What we are building

A small Python City Brain that other layers can call over MCP. It consumes reported readings, detects incidents, asks a free AI API for a typed action proposal, validates that proposal, obtains Guardian approval for the exact request, and asks Twin to act. Brain never acts directly and never performs containment.

The source tree is a runnable **development scaffold**, not a completed mock. The business functions deliberately raise `NOT_IMPLEMENTED`. Green bootstrap checks establish that the environment works, not that the mock is delivered.

Primary workflows: congestion -> R1 signal request; medical/fire -> R2 dispatch; high water -> R3 valve request with preview. Also cover the other incidents in the CIVIS table, with alerts or explicit blocked decisions when prerequisites are absent. All five domains remain represented. Telecom and Waste are outside this checkpoint.

## Four branches, one repository

| Member | Branch | Exact work | Task card |
| --- | --- | --- | --- |
| Elyes | `codex/civis-elyes` | Integration branch, shared interfaces, live MCP clients, trust gate, action validation, logging, final release | [ELYES.md](ELYES.md) |
| Yassine | `codex/civis-yassine` | Input normalization and deterministic incident detection | [YASSINE.md](YASSINE.md) |
| Meriem | `codex/civis-meriem` | Free Gemini API adapter, prompt, typed and constrained proposals | [MERIEM.md](MERIEM.md) |
| Maram | `codex/civis-maram` | Recorded AI responses, fake Twin/Guardian, workflow tests and handover evidence | [MARAM.md](MARAM.md) |

Yassine, Meriem and Maram open PRs **into `codex/civis-elyes`**, not `main` or `brain`. Elyes reviews and merges them sequentially. The final release goes from `codex/civis-elyes` to the triplet's `brain` branch. Other teams continue using their own layer branches.

Only Elyes changes shared models, dependencies, environment settings, server wiring and CI. Members may add helper files only under their assigned folders. CI checks the allowed file list from the integration branch. This reduces file conflicts; frozen function signatures and tests address integration conflicts. Nobody can promise that arbitrary edits will never conflict.

## Schedule and meeting checklist

| When | Deliverable | Owner |
| --- | --- | --- |
| 7 Oct, team meeting | Everyone checks out their branch, installs the same environment, runs bootstrap tests, explains their input/output function | All |
| 7 Oct, end of meeting | Freeze Guardian tool map, confirm Twin `params`/dispatch schema, choose mock preview policy, collect GitHub usernames | Elyes |
| 8 Oct, 12:00 | First small draft PR: one completed function plus one meaningful test; post progress in own file | Each member |
| 8 Oct, 20:00 | Detection and planning unit PRs ready; fake peers implement the first three fixture workflows | Yassine, Meriem, Maram |
| 9 Oct, 12:00 | Elyes merges reviewed unit PRs, wires orchestration and callbacks; Maram updates her branch and completes end-to-end tests | Elyes, Maram |
| 9 Oct, 18:00 | Run complete acceptance matrix, one live Gemini smoke test, and real partner discovery/auth smoke tests | Elyes, supported by team |
| 9 Oct, 20:00 | Release candidate, launch instructions, example payloads and limitations ready for partners | Elyes |
| 10 Oct | Reserved for partner feedback and fixes, not first integration | All |

First meeting: spend 10 minutes on Brain/Twin/Guardian roles, 15 on setup, 20 walking through task cards and one sample payload, then 15 on the three workflows and blockers. Each member must explain what their function receives, returns, and is forbidden to do.

## Handover definition

- A fresh clone starts with the documented commands on Python 3.12.
- Health and capabilities distinguish readiness from mere process availability.
- Partner tool names, auth keys, URLs and capability flags are configured, not buried in code.
- Tests run without network access or API keys, using fixture AI and local fake peers.
- A separate live Gemini check proves the real AI adapter works; free quota errors become blocked decisions.
- Missing approval, untrusted evidence, invalid AI JSON, unsupported preview and cap rejection never actuate.
- Exact action/targets/params approval, idempotency and optional pending/commit handling are tested.
- Read-only incident/explanation tools and Guardian containment notifications are available or explicitly reported unsupported.
- Every run produces a JSONL decision trace. The shared triplet log format remains a separate agreement; the mock format must be labelled.
- Other teams receive the actual branch/commit, launch command, MCP URL, input example, tool list and known limitations. Do not claim fixtures prove live integration.

## Read first

1. [SETUP.md](SETUP.md)
2. [CONTRACT.md](CONTRACT.md)
3. Your task card
4. [REVIEW.md](REVIEW.md), [ACCEPTANCE.md](ACCEPTANCE.md)
5. [PARTNER_GAPS.md](PARTNER_GAPS.md)

Business implementation, a dashboard, full city simulation, databases, deployment infrastructure and v1.0 security are not completed by this setup. The shared dashboard is Trinity's responsibility. A free AI API is used at runtime; AI coding assistants may help implement each member's assigned module.
