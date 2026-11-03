# brain-mock-2 validation

20 October 2026. Partner sources: `origin/main` at `cf6f1dcb25796e64d22e96b3fe6ab8779f00a0b0`. The complete partner archive contains 120 files; none were changed. All release changes are under `brain/`.

| Check | Result | Meaning |
| --- | --- | --- |
| Brain regression suite | 336 passed | Five scenarios, MCP authorization, schema checks, recovery, replay, stale evidence, tokens, preview, live setup and private configuration separation |
| Actual partner integration controls | 14 passed | Real Twin MCP/SSE, advancing clock, configured app startup without fixture files, low-trust recovery; positive actions use an explicit test Guardian |
| Required partner security acceptance | 1 passed, 8 failed | Five Twin token-claim failures and three Guardian boundary failures remain visible |
| Live Gemini + actual Twin | Medical committed, one dispatch | 6.91 seconds, seven SSE batches received during planning; approval came from a test Guardian |
| Ruff | Passed | No lint findings |
| Credentials | Kept outside Git | Private `.env.partner` plus separate Dali/Houssem role files |

The live AI test exposed a CIVIS mismatch: the general Twin manifest allowed multiple units while S05 permits one ambulance. Brain now constrains the AI schema before planning and still validates the returned proposal. A controlled regression verifies the schema bound. Earlier failed diagnostic attempts are not counted as successes.

All eight security acceptance failures were reproduced against the actual partner snapshots. They remain ordinary failing assertions. The final control rerun passed after the CIVIS fixes; it does not turn those failures green.

Evidence files are supplied separately as `CIVIS_brain-mock-2_evidence.zip`: JUnit summaries, sanitized scenario outcomes, the live Gemini result, source versions and reports. No key, full approval token, private environment or raw server log is included.

## Reproduce

From `brain/`, using Python 3.12 and the committed lock:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests mocks scripts interop
~~~

For real partner controls and required acceptance checks, follow `interop/README.md`. Guardian runs in its separate dependency environment; Twin's integration environment includes its declared requirements. No source patches or frozen clock are used by the current controls.

## Acceptance still blocked

Real Guardian score/token APIs, native ingestion and real containment callbacks are missing in this release checkpoint. Twin already supplies vehicle_count (cars/min) and avg_speed (km/h); CIVIS expects congestion_index (%), so the teams must align and test the input policy. The five Twin token-claim checks need fixes. Two-step remains off pending its real tool. Water valve choices require joint configuration. Final reaction-time/freshness limits need agreement. Runtime state is in memory; use a fresh Twin run after restart. See the 23 October audit for the later Guardian v2 adapter and evidence.

The neighbour/later-tick/fresh-verdict sequence is implemented and tested against the adapter contract and actual Twin with test scores. It cannot yet be certified against Guardian's missing assessment API. Pushed verdict streams and grid-switch responses are outside the reduced mock. The five scenarios and MCP endpoints are delivered; the complete final-version architecture is not being declared accepted.
