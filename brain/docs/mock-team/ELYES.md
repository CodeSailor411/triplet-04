# Elyes: integration, trust boundary and release leadership

Branch: `codex/civis-elyes`, also the team's integration branch. You retain root/layer ownership as CodeSailor411. Three members send PRs into this branch; you review before merging. Do your leader changes directly on this admin-owned branch only after local checks, or coordinate a reviewed leader PR later.

## Your files and important work

Own shared `contracts.py`, `ports.py`, `settings.py`, `app.py`, `integration/`, `tests/integration/`, dependency pins/lock, setup scripts, ownership policy, interface card, launch/readme, CI and release evidence. Do not edit other members' active module files behind their branches; route fixes through their PRs. Avoid all `twin/` and `guardian/` implementations.

## 7 October: freeze the ground before parallel coding

1. Verify GitHub usernames and grant write access. Everyone clones using their own account, checks out the assigned branch and runs setup/tests. Confirm the selected Python interpreter.
2. Walk through one typed reading, one candidate incident, one Plan and one Decision. Keep function signatures and error contracts fixed until all three member PRs land.
3. Resolve the specific questions in PARTNER_GAPS.md. Obtain Guardian's actual schemas and one token example; do not build on guessed tool names, score range or cut-offs.
4. Confirm current Twin `params`, `destination`, unit type `fire`, and action carrier IDs. Record partner commit/protocol versions in the handover.
5. Decide the preview gap explicitly with Trinity: missing required preview blocks live R3/grid requests until a minimal preview or an agreed mock exception exists. Fixture-only preview is not evidence of live support.

## Implement your own runtime in this order

1. **Live MCP adapter:** implement a `ToolPeer` adapter under integration using the pinned SDK and `httpx2`. Read URLs/keys from settings, attach each partner's Brain Bearer key, enforce timeouts and validate protocol `2026-07-28`. Discover available tools at startup; refuse missing Guardian map values.
2. **Bootstrap context:** fetch Twin clock, nodes and action manifest. Cache only within the current run; invalidate on run/reset or changed capabilities. Do not assume capabilities already publishes all numeric caps: current action limits are in `list_actions`, complete shared-domain limits are a partner gap.
3. **Input/evidence handling:** call Yassine's function with per-run state. Ask Guardian to assess relevant readings through the adapter. Use its numeric scale/cut-offs only when supplied. Keep original evidence IDs. No usable trusted alternatives means blocked/no actuation.
4. **Mock retry policy:** at most three distinct attempts using later ticks or alternate relevant sensors, with a bounded window specified in your mock config. Do not count three identical cached calls as three new readings. Label this definition as the primary mock's working choice and confirm it with partners before the joint run. No human-review UI or workflow here.
5. **AI planning:** call Meriem through an injected provider after evidence selection. Fixture provider for CI; configured free Gemini for the smoke test. Enforce per-run call budget and timeout. Treat provider failures as blocked outcomes, never implicit approval.
6. **Deterministic plan validation:** check known action, carrier IDs, allowed parameter names/types/enums/bounds, evidence references and current manifest risk/preview flags. Never trust the AI's risk value or claimed preview result. Reject containment proposals and instructions embedded in data/tool metadata. Do not invent unavailable dispatch units or hydraulically safe changes.
7. **Approval/execution:** obtain Guardian's token for exactly the normalized action, target set and params using Twin's run/clock. Brain does not mint a token or convert a score to permission. Obtain required preview if supported and safe; otherwise block. Request Twin `actuate` with a stable idempotency key. Keep Twin's refusal code/details intact.
8. **Optional pending:** if response is pending, discover the confirmation tool and confirm once under its actual contract. If unavailable, leave pending and explain it. Do not label a pending action committed or repeat a fresh actuation to force completion.
9. **Idempotency:** cache handled run/tick inputs and command identities. Same unchanged intent keeps the key; modified intent requires a new key and new approval. On timeout after sending, reconcile or retry that same logical request; never make a new key and accidentally double-execute. Do not split a cap-refused intent into smaller requests to bypass the limit.
10. **State/log tools:** wire evaluate_tick, active incidents, explanation lookup and Guardian-only notify_containment. A containment notice invalidates affected pending evidence and prevents stale queued plans; Brain never calls isolate/quarantine/rollback/release. Return honest unsupported status for unimplemented optional features.
11. **Logs/readiness:** append mock JSONL observation/trust/proposal/decision/action events with run/tick/evidence/code; redact keys/tokens. Map to Trinity's shared log when supplied. Set `ready=true` and implemented tool list only after the acceptance matrix passes. Update the bootstrap health test appropriately when readiness becomes conditional.

## Your review and integration order

- Review Yassine's module first, then Meriem's. Check contracts and test evidence; merge one PR at a time.
- Ask Maram to merge the refreshed integration branch into her own branch before final workflow testing.
- Run all tests after every merge. Shared contract changes require your commit, an explicit note to all three members, and re-running affected tests.
- Members request your review, not approval from a random teammate. Resolve conversations, re-run checks, approve, then merge. Do not approve a PR just because its AI assistant says it works.
- Final release: after candidate checks, have Maram open the PR from `codex/civis-elyes` into `brain`, so you can review it. GitHub does not let a PR author approve their own PR. Keep root permissions and Brain CODEOWNERS assigned to you.

## Your tests and deadline

In `tests/integration/`, cover inbound auth, wrong caller, missing/mismatched token, discovery mismatch, required-preview absence, cap refusal, idempotent retries, pending/commit, and containment invalidation. Maram's workflow tests prove the complete composition.

By 9 Oct 12:00 integrate unit PRs. By 18:00 complete the full matrix and one synthetic live Gemini call. By 20:00 prepare partner handover and the release PR. Deliver the URL/key exchange privately yourself; no real key belongs in Git or a shared document.

## Prompt to give your AI coding assistant

> I am Elyes, CIVIS leader. Read the frozen CONTRACT, ELYES card, PARTNER_GAPS and ACCEPTANCE. Implement only integration/shared environment/server/tests files assigned to me. Leave Yassine's detectors, Meriem's AI planner and Maram's fixtures to them. Compose their fixed interfaces, enforce discovered schemas/caps/preview and exact-action Guardian token requirements, handle pending/idempotency/timeouts, and preserve evidence in redacted logs. Never invent partner tool names or safety thresholds. Work in small tested changes and keep readiness false until the primary mock acceptance tests pass. Explain unresolved partner assumptions before coding around them.
