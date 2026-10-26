# Joint acceptance: CIVIS integration

Updated 27 October 2026. Test runs retain their original UTC timestamps.

Working branch: `codex/civis-elyes`. Published checkpoint `brain-mock-2` is unchanged. Dali's reported 336-test result describes that checkpoint, not the newer development branch. Use this branch with the updated private partner configuration for the next joint run.

## Versions and evidence

| Layer | Latest fetched tag | Source commit |
|---|---|---|
| Twin | `twin-mock-3` | `b012c94e4a63652c7fbe9b6baf62ce59b4a1ac9c` |
| Guardian | `guardian_mock_v3` | `526f8f64970ded02319cf0763cf03a8159f085f0` |

The Guardian annotated tag object is `333f8bf`; it is not the source commit. Partner code is extracted unchanged into ignored, fresh per-run directories. Newer `origin/twin-integration-3` also contains graph work; it is not silently substituted for the tagged acceptance build. A locally patched ZIP is a different build and needs its own exact commit/tag for reproducibility.

The completed results and evidence paths are below. Unit tests and recorded plans do not certify real joint authorization.

## CIVIS changes

- Adopt Guardian's actual tools: `describe_capabilities`, `get_trust_verdict`, `authorize_action`. The fixed v3 adapter maps fields and calls once per original reading ID; it does not require a new batch API.
- Default live transport and public/private setup now select v3 on port 5000, with the contract enabled. Existing files containing `GUARDIAN_CONTRACT_CONFIRMED=false` must be migrated; Python defaults cannot override an explicit old value.
- Read `guardian_verdict_policy` for the inclusive reading cutoff and risk minima. Normalize the published `[0,1]` verdict scale and preserve refusals. Do not lower Guardian's floors.
- Retry read-only fresh verdict retrieval on explicit unavailability or a generic tool error, bounded by monotonic time and three attempts per ID. A persistent generic error remains `PEER_ERROR`, cause unknown. Denials and malformed scores remain terminal; authorization is not retried. No score, observation or token is invented.
- Supply an explicit S02 mock command list: `WAT-01` incident, target `WAT-01`, valve position `40` on the advertised `0..100` percent scale. Current seed, sensor unit, Water-only carrier, manifest, R3, preview and caps are checked in preflight and the runtime before planning.
- Preserve exact Guardian `g1` tokens, current Twin simulated clock, source IDs, risk and idempotency bindings. Brain has no signing key and performs no containment.
- Replace contradictory historical interface text with one current card and this detailed handover. Correct both Guardian credential aliases in role files.

The Water policy is a CIVIS virtual-command acceptance policy, not proof of hydraulic safety or flood reduction. Twin's actuators do not alter its sensor dynamics. S07 remains disabled; no supply roles, local datum or supply-preserving direction is fabricated. Power and Air Quality remain alert-only for the agreed five-scenario gate. New graph/GNN features are outside this integration change.

## Run the actual services

Use Python 3.12 and the committed `requirements-lock.txt`; do not upgrade one layer independently. Start Twin and Guardian from the exact delivered versions. Start Guardian's own Twin SSE bridge as its README requires. Brain does not ingest readings on Guardian's behalf.

From `brain`, create a local `.env.partner` using `config/partner.env.example` and the separately exchanged credentials. The important selections are:

```dotenv
PEER_MODE=live
LLM_MODE=gemini
TWIN_FEED_ENABLED=true
GUARDIAN_TRANSPORT=mcp_v3
GUARDIAN_MCP_URL=http://127.0.0.1:5000/mcp
GUARDIAN_CONTRACT_CONFIRMED=true
GUARDIAN_VERDICT_WAIT_SECONDS=1.5
MOCK_INTEGRATION_PROFILE=true
SCENARIO_POLICY_FILE=config/integration/twin-mock-3.json
```

`GUARDIAN_SCORE_TOOL=get_trust_verdict` and `GUARDIAN_TOKEN_TOOL=authorize_action` state the wire names in the template. The fixed `mcp_v3` adapter uses those published names directly; these settings only customize the historical mapped `mcp` transport. No mapping JSON is required for v3.

Windows, from `brain`:

```powershell
.\.venv\Scripts\python.exe -m civis_brain.preflight --env-file .env.partner
.\.venv\Scripts\python.exe -m civis_brain --env-file .env.partner
```

Linux, from `brain`:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m civis_brain.preflight --env-file .env.partner
.venv/bin/python -m civis_brain --env-file .env.partner
```

Preflight is read-only and checks connection/policy prerequisites, not signed-action acceptance. On a shared network replace localhost URLs and bind hosts explicitly. The shipped tests here run on Windows; Linux commands are provided without claiming a Linux rerun.

Credential pairs: Brain `TWIN_BRAIN_KEY` = Twin `TWIN_KEY_CITY_BRAIN`; Brain `GUARDIAN_BRAIN_KEY` = Guardian `GUARDIAN_BRAIN_MCP_BEARER_KEY`; Brain `BRAIN_GUARDIAN_CALLER_KEY` = Guardian's outbound `GUARDIAN_BRAIN_BEARER_KEY`. The latter sets a credential only, not a containment callback implementation. Guardian's ingestion/API credential is separate. Guardian supplies Twin its public Ed25519 verification key; compare fingerprints. Brain receives no private signing key.

## Required joint gate

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/test_tagged_v3.ps1 -IncludeBrainTests
```

The runner resolves tag objects to source commits, freshly extracts partner files, synchronizes the isolated combined environment without relaxing Brain pins, and records source/dependency manifests. It fails when required partner assertions fail. `-DiagnosticsOnly` explicitly cannot certify acceptance.

New shipped-service controls construct Brain through Settings/bootstrap/FastAPI, consume independent native Twin SSE in Brain and Guardian's delivered bridge, and call Brain's inbound MCP tools. S03 exercises the agreed `POWER_EVIDENCE_UNCONFIRMED` warning path, which does not request a Guardian verdict. S04 requires a trusted sustained-pollution alert, not an input warning. A clearly labelled recorded planner replaces only external AI generation. No Guardian score/token or peer is replaced. Positive incident inputs use Twin's public native sensor-model baseline configuration, not spoofed `fake_reading` attacks. The latter remain diagnostic refusal inputs.

Required coverage: five native workflows (S01/S02/S05 authorized commands, S03/S04 alerts), refusal, stale evidence, exact duplicate with one effect, reconnect/gap invalidation and actual Guardian containment followed by Brain invalidation. A failed authorization prerequisite prevents certifying duplicate/action acceptance, even when local controls pass. Logs and source manifests distinguish those outcomes.

## Partner corrections

Confirmed by reading unchanged Guardian v3 source; live reproduction is separated in the results below:

1. `twin_adapter.py`: unpack the two values returned by the pinned MCP transport; discovery currently expects three.
2. `twin_discovery.py`: read `is_error` and `structured_content` from MCP results.
3. `unified_api.py`: read the Twin actuator field `action`, not `name`.
4. Refresh the Twin simulated clock when authorizing. Do not freeze expiry against the discovery snapshot taken at startup.
5. Score native `units_free` evidence, including the `ambulance` channel. Medical requires current resource evidence; Brain cannot replace it with trust in incident readings.
6. Connect R3 valve authorization to the actual Twin `preview_action` contract. Guardian currently explicitly refuses with `safe_preview_tool_unconfirmed`.
7. Return missing-verdict availability as a declared structured code or MCP `ToolError`. MCP 2.3 masks the current plain `ValueError('verdict_not_found')`; Brain cannot reliably classify that generic error as a feed race.
8. Implement real containment and the existing Brain callback. Guardian's interface currently marks them proposed. Local Guardian state is not evidence of Twin containment.
9. Fix historical fresh reassessment: `scoring.py` excludes the original ID but leaves newer timestamps in history; `violates_rate_of_change` compares the old reading to the latest entry and clamps negative time to 0.001 seconds. Filter and order the historical comparison window before the original reading. Keep current containment and reputation checks. The exact cached/fresh discrepancy is reproduced below.

Policy remains with 9antra: the reading cutoff is 0.7, with separate action minima. The captured 0.65 cases are explained by the fresh historical rate check; do not treat the ingestion score as the fresh score or lower the cutoff to conceal this defect. A spoofed-reading refusal alone is not proof that scoring is wrong.

Twin's real `congestion_index` exists in mock3. Prior five token-claim defects were fixed in that tag and must not be repeated as current failures without a new reproduction. Geographic links and straight-line distances do not establish Water controls or hydraulic direction. Keep `INTERFACE.md`, `tools/list`, capabilities and the tested source tag consistent in every layer.

## Validation results

Final complete run: `brain/.artifacts/tagged-v3/20261026T193224391Z-0b4ad268/`.

| Check | Result |
|---|---|
| CIVIS regression suite | **522 passed**, zero failures/skips |
| Ruff | Passed |
| Python / Brain dependency lock | 3.12.13; all 55 applicable pinned packages match |
| Joint checks against unchanged tags | **16 passed, 13 failed**, zero errors/skips |
| Full three-layer acceptance | **Not passed** |

The 29 checks comprise 18 transport/security/explicit-ingestion diagnostics and 11 shipped-service controls. Recorded planning is labelled; no live Gemini request was made in this change. Earlier failed iterations remain in separate directories. One unit assertion was corrected to enforce at most three calls, since the real-time deadline can legitimately stop a loaded machine after fewer attempts; runtime limits were not relaxed.

| Live scenario | Observed result | Owner / reason |
|---|---|---|
| S01 Traffic | Blocked | Guardian fresh retrieval/trust; diagnostic authorization also reports `twin_discovery_unavailable` |
| S02 Water | Blocked | Guardian fresh retrieval/trust and discovery; its R3 preview refusal is an additional source-confirmed blocker |
| S03 Power | Passed within reduced scope | CIVIS evidence warning only; no threshold or outage is invented, no Guardian trust exchange claimed |
| S04 Air Quality | Blocked | Fresh Guardian reassessment fails the reading cutoff even after native ingestion; not merely a startup delay |
| S05 Medical | Blocked | Guardian does not score the required native `units_free` evidence |

Passing joint controls include all six Twin signed-claim controls, signed g1 wire acceptance with a clearly labelled test signer, real Guardian tool/verdict discovery with explicit diagnostic ingestion, reduced diagnostic Power/AQ alerts, unauthenticated legacy mutation refusal, native Power warning, missing-evidence refusal, stale action-capable feed blocking, reconnect/evidence invalidation, and actual Guardian/Twin public-key matching.

Failed checks are not thirteen independent bugs. Discovery, missing availability evidence and fresh reassessment cause multiple workflow failures. The duplicate-action check cannot obtain the initial approved action, so it does not establish a Twin idempotency bug. The containment request returns Guardian's local simulated state but does not reach Twin; Brain therefore has no real Twin change to invalidate. No real Guardian-approved action was committed.

Two additional failures concern legacy HTTP routes, not a proven bypass of current MCP action authorization: rollback still exposes the original trusted score, and an authenticated ingestion caller can disable reading signature checking. 9antra owns their intended policy and correction.

A separate fair S04 observation captured 24 Brain batches and 23 Guardian batches with no dropped feed data. All 16 exact initial refusal IDs had ingestion audit scores 1.0, yet fresh retrieval/recovery did not produce a qualifying alert. Do not report those ingestion values as fresh scores or conclude that every fresh reading is 0.65. A subsequent actual-MCP capture confirms three exact cached/fresh pairs: **1.0 becomes 0.65**, all with `rate_of_change_exceeded`. [Sanitized raw replies and native history](evidence/guardian-fresh-history-2026-10-27.json). For AIR-01 at tick 8, 132.1 follows 131.9 at tick 7: 0.2 units/second. Newer tick 9 is 132.6. Comparing tick 8 backward against tick 9 with the 0.001-second clamp produces 500 units/second and an erroneous penalty against the configured maximum 50. This is a Guardian historical-window defect, not a Brain score conversion. The same-unit source values and exact reading ID are preserved.

**CIVIS limits kept visible:** only the five reduced scenarios form this checkpoint; S06-S08 live policies remain disabled. S02 validates a virtual command, not hydraulics. Power is an evidence-warning path. State remains in memory. Live Gemini and a Linux run were not repeated. None of these is silently promoted to completed functionality.

Publish this as the explicitly limited `brain-mock-3` checkpoint on `codex/civis-elyes`. `main` and `brain-mock-2` remain unchanged. Partner corrections require a newly tagged build and another gate run.
