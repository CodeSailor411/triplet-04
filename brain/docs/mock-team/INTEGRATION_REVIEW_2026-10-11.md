# CIVIS integration review, 11 October 2026

**Disposition:** all three submissions are merged and corrected locally on codex/civis-elyes. No push, remote PR merge, remote review approval or change to main was performed. The local five-scenario mock passes its checks; full partner acceptance remains pending.

Review basis: the frozen Brain contract, existing implementation, 9 October meeting report, and actual Twin main at 9170ee2. Document proposals were not treated as permission to implement partner code or add human review.

## Individual submissions

| Submission | Reviewed head | Original test result | Main findings and local correction |
| --- | --- | --- | --- |
| Meriem, S02 Water, PR #5 | 6f294b8 | 37 scenario tests passed | Valve fixtures used position_pct/percent instead of Twin's position/%; detector accepted an unexpected channel; planner repeated weaker parameter validation and accepted incomplete persistence evidence. Corrected vocabulary/channel handling, used the common manifest validator, retained all evidence and validated policy bounds. |
| Maram, S05 Medical, PR #6 | 3258ed4 | 18 unit tests passed; 2 workflow tests failed | Availability used a null channel instead of ambulance; manifests used incompatible string types; Guardian/cap fixtures were incomplete; workflow expectations did not match the actual runner. Corrected fixture contracts and semantic assertions, reused common validation, required current whole-unit availability, retained evidence across carrier choices and bounded history. |
| Yassine, S01 Traffic, branch submission | c9301db | 9 unit tests passed; no workflow test | Nodes/actions/batches were empty; two JSON files contained a BOM; the local parameter validator rejected Twin's choice type; policy silently defaulted thresholds; channel/range checks were absent; persistence kept only two IDs and dropped shared domains. Completed runnable fixtures, reused common validation, constrained policy/inputs, retained the complete bounded evidence window and domain memberships, and added workflow/refusal tests. |

PRs: [Meriem #5](https://github.com/CodeSailor411/triplet-04/pull/5), [Maram #6](https://github.com/CodeSailor411/triplet-04/pull/6). Yassine had no open PR at review time.

Additional Traffic fixes: stale ticks do not rewind state; conflicting sensors do not select an arbitrary first value; absent congestion_index produces an explicit warning for speed/count input; proposed signals must use a discovered incident-linked carrier. The obsolete rule rejecting words such as "quarantine" inside explanatory text was removed; action semantics are validated instead.

These were integration defects despite passing unit tests. Original authors' scenario classes and branch history are retained. Shared execution remains in Elyes's runtime. No dependency upgrades, partner implementation edits or extra scenario types were introduced.

## Shared corrections

- Identically named test modules now have package boundaries, so full-suite collection works.
- All actionable scenarios use the same discovered parameter validator. Required names, types, bounds and unique target/evidence IDs are checked once in the common contract path.
- Tokens now use simulated UTC iat/exp and a maximum 60-second lifetime, rather than integer ticks. Normalized token score matches current Twin claims; Guardian assessment thresholds remain explicitly configured fixture values.
- Brain polls Twin containment state before detection and execution and invalidates affected evidence. It never invokes isolation, quarantine, rollback or release.
- Per-run logs use run-logs/<run_id>.brain.jsonl and the meeting envelope: run_id, event_id, timestamp, tick, wall, layer, event_type, caused_by, data. Decision data includes idempotency_key; reading IDs supply causal links. Secret material and hidden truth are redacted.
- The interface exposes the five actual scenarios, each with base/refusal inputs and the same request/response trace. The previous synthetic signal case remains an internal regression fixture, not a sixth scenario in the menu.

## Verification

| Level | Result | What it proves |
| --- | --- | --- |
| Automated suite | 264 passed, zero skipped; Ruff passed | Scenario behavior, common guards and regressions under controlled inputs |
| Windows environment | Python 3.12.13; 55 applicable pins match; dependency check passed | Brain environment is consistent with its committed lock |
| Mixed five-scenario runtime | Passed | Separate scenario state and contexts; signal/valve/dispatch each commit once; Power/Air alert; duplicate tick adds no work or effect |
| Real localhost HTTP/MCP | Six Traffic/Water/Medical base/refusal workflows passed through Brain and two peer servers | SDK discovery, auth, request serialization, evidence, decisions and effects; partner logic is still a stand-in |
| Browser | All five base/refusal presets passed, edited reading prevented action, desktop/mobile checked with no JavaScript errors or overflow | Controls submit actual editable requests and show the evaluated result |
| Live Gemini | S01, S02 and S05 base each passed with one real Interactions request and one simulated effect | Actual API, structured Plan validation and downstream mock workflow |
| Actual Twin main 9170ee2 | Four compatibility outcomes below passed | Current Twin code over MCP and its log merge utility, with synthetic data/test Guardian |

Actual Twin outcomes:

| Case | Observed result |
| --- | --- |
| Medical, approved | committed, exactly 1 Twin commit |
| Medical, denied | GUARDIAN_DENIED, 0 commits |
| Water, required preview missing | PREVIEW_UNAVAILABLE, 0 commits |
| Traffic, current speed/count feed | EVIDENCE_WARNING for missing congestion metric, 0 commits |

Adversarial tests cover malformed counts/IDs/run/ticks, null/NaN, wrong units/channels, missing/full persistence evidence, invalid AI parameters/carriers, shared-node caps, duplicate commands, later repeated refusals, expired/future/mismatched tokens, containment changes during approval, clock changes, optional pending confirmation, uncertain outcomes, API errors/timeouts/budget and disk write failure. This is broad regression coverage, not a claim to prove every possible edge case.

Reproducible commands from brain/:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=.artifacts/integration-tests.xml
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
.\.venv\Scripts\python.exe scripts/doctor.py
.\.venv\Scripts\python.exe scripts/run_case.py --scenario S01 --case base
~~~

Repeat run_case for S01-S05 and base/refusal. Local detailed evidence is in ignored .artifacts/integration-tests.xml, .artifacts/debug/review-*.json and .artifacts/partner-compatibility/. It is not uploaded.

## Remaining partner work and discrepancies

1. **Real Guardian:** actual tools, mapping, thresholds/score scale, approval request/time, token signing mode and caller key have not been exercised. A test Guardian is not evidence of 9antra integration.
2. **Traffic:** current Twin has vehicle_count in cars/min and avg_speed in km/h, not congestion_index in percent. Do not invent a conversion. Agree an additional metric or a documented detector rule.
3. **Water:** current Twin advertises required preview but exposes no preview tool. Positive Water execution is therefore fixture-only.
4. **Timing/retries/pending:** the meeting's neighbour-first sequence, waits and total pending deadline remain unfinished. Existing low-trust handling is bounded to distinct ticks; the AI timeout is 60 real seconds, peers 5 seconds. This does not establish the Phase 1 ten-second reaction requirement. Twin code and the meeting differ on when two-step confirmation is available; discovery is authoritative for runtime calls.
5. **Scores/caps:** meeting score floors are still placeholders awaiting 9antra. Fixture cut-offs are not claimed as agreed production values. Read all touched-domain caps from discovery; missing limits block.
6. **Human escalation:** the meeting mentions a human step, while Elyes explicitly excluded human review for this mock. No human-review workflow was added. This needs team clarification.
7. **Restart/driver:** state is in memory and Twin does not automatically send Brain batches. Use a scenario driver; restart with a fresh run ID. Do not claim durable recovery.

## Next steps

Elyes can review the local build at http://127.0.0.1:8001/ using Recorded response first. After approval, publish the integration branch and reconcile the member PRs through the established review flow. Hold the release into brain/main until partner limitations are accepted or resolved and the joint smoke test is complete. Teammates should bring the approved integration changes back into their own branches before continuing shared-contract work.
