# CIVIS Brain mock 3

27 October 2026. Tag: **brain-mock-3**. Branch: **codex/civis-elyes**.

This checkpoint publishes the working CIVIS changes for partner testing. **Full three-layer acceptance remains blocked.** It is not a completed joint release.

## Use the correct layer versions

Extract `brain/` from `brain-mock-3`, `twin/` from `twin-mock-3`, and `guardian/` from `guardian_mock_v3`. Each tag identifies its own layer; historical partner folders elsewhere in the CIVIS tag are not the tested partner versions.

| Layer | Tested source |
|---|---|
| Twin | b012c94e4a63652c7fbe9b6baf62ce59b4a1ac9c |
| Guardian | 526f8f64970ded02319cf0763cf03a8159f085f0 |

No partner implementation was modified. The [interface card](../../INTERFACE.md) lists the actual Brain tools. The [joint report](JOINT_ACCEPTANCE_2026-10-26.md) contains reproduction commands, evidence and ownership of failures.

## What CIVIS delivers

- Guardian v3 mapping: `describe_capabilities`, individual `get_trust_verdict` and `authorize_action`; exact score, risk, evidence and refusal-field translation.
- Working live configuration defaults and migration, correct Guardian credentials, independent Twin SSE reception and explicit environment-file loading.
- Bounded read-only verdict retries with sanitized attempt logs. Invalid scores and denials remain terminal. Brain never issues or signs approval tokens.
- Original `g1` token forwarding, Twin simulated-time checks, exact action/evidence/idempotency binding, required preview and containment invalidation.
- Explicit virtual Water command allowlist: WAT-01 to WAT-01, valve position 40 percent, seed 42. Current discovery is validated before planning. This is not a hydraulic safety model.
- A reproducible real-service gate with native Twin conditions, real Guardian ingestion, inbound Brain MCP calls, and committed-receipt checks. Recorded planning is labelled; it does not replace either peer.

## Start Brain

Python 3.12; install the committed lock without independent upgrades. Obtain the private `.env.partner` separately. From `brain`:

```powershell
.\.venv\Scripts\python.exe -m civis_brain.preflight --env-file .env.partner
.\.venv\Scripts\python.exe -m civis_brain --env-file .env.partner
```

Linux uses `.venv/bin/python` with the same module arguments. See the joint report for installation and peer setup. Start Guardian's own Twin feed bridge. Use `GUARDIAN_TRANSPORT=mcp_v3`, `GUARDIAN_CONTRACT_CONFIRMED=true`, `TWIN_FEED_ENABLED=true`, and the supplied mock policy. Ordinary `.env` and browser presets are for isolated developer replays.

## Validation and limitations

**522 CIVIS tests pass; Ruff passes.** Python 3.12.13 and all 55 applicable locked packages were verified. The complete joint run has **16 passing and 13 failing checks**, without skips. The failures group into Guardian discovery, verdict availability/reassessment, missing resource evidence, real containment and legacy HTTP checks; they are not thirteen independent defects. A duplicate-action check is blocked before its first approval, so no Twin idempotency defect is inferred.

S01, S02, S04 and S05 do not pass the native end-to-end gate. S03 passes its agreed evidence-warning path, without claiming a trusted Power incident or switching. S06-S08 live policies remain disabled. S02 proves a permitted virtual command only. State is in memory. Live Gemini and Linux were not rerun for this checkpoint.

Main and brain-mock-2 are preserved. Partners must publish corrected tagged builds before full acceptance can be rerun and claimed.

## Development branch follow-up, 3 November 2026

These checks are on local `codex/civis-elyes` after the `brain-mock-3` checkpoint. They are not part of that tag. Twin source was `twin-mock-3` at `b012c94e4a63652c7fbe9b6baf62ce59b4a1ac9c`; Guardian source was `guardian_final_version` at `f23e570bf1685e155ad8ecb73cd73ef83e259fcb`.

| Check | Result |
| --- | --- |
| S01 latest-reading recheck | High congestion remains eligible and commits once. A newer cleared reading still blocks with `EVIDENCE_CHANGED`. Runtime safety logic was not relaxed. |
| Live traffic graph interpretation | Passed with Gemini Flash-Lite. Twin forecast was ready for 11 nodes and 110 source readings. The interpretation is read-only and is not action evidence. |
| Brain tests and Ruff | 555 tests passed; Ruff passed. |

The first graph-test attempt hit `httpx.ReadTimeout` while polling the Brain `/health` endpoint with a 3-second test timeout. It did not record a Gemini `AI_TIMEOUT`. The live test now waits for the runtime forecast and interpretation state directly; the rerun passed. No Gemini adapter change was needed.

The standalone S01 partner acceptance check remains inconsistent. One run committed after a newer high reading; another was blocked by Guardian `get_trust_verdict` errors, including `verdict_not_found` and `PEER_UNAVAILABLE`. The stable Twin test profile addresses the S01 test stimulus, but does not clear this Guardian issue or make joint acceptance green.

## Main candidate verification, 3 November 2026

The Brain-only main candidate was checked against the exact latest available partner tags: Twin `twin-mock-3` at `b012c94e4a63652c7fbe9b6baf62ce59b4a1ac9c` and Guardian `guardian_final_version` at `f23e570bf1685e155ad8ecb73cd73ef83e259fcb`.

| Check | Result |
| --- | --- |
| Brain tests | 555 passed |
| Ruff | Passed |
| Tagged Twin and Guardian workflow gate | 22 passed, 8 failed |
| Live Gemini interpretation of Twin-fed traffic forecast | 1 passed |

The eight joint-gate failures cover S02 and S05 action prerequisites, Guardian scoring for actual `units_free` evidence, Guardian rollback retaining a stale trusted score, Guardian allowing an authenticated caller to disable reading signature validation, and Guardian containment not propagating to Twin and Brain. These are partner integration failures; the end-to-end S02 and S05 workflows remain blocked. This result does not certify full three-layer acceptance.

The live graph check used the real Twin feed and Gemini Flash-Lite. It produced forecasts for 11 Traffic nodes from 110 source readings and a separate read-only interpretation. The graph output never entered planning or authorization. The forecaster is a GraphSAGE-style research prototype trained on deterministic synthetic Twin data. Its held-out metrics show no meaningful improvement over the temporal MLP without graph input, and do not validate real-world traffic prediction.

Reproduction command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/test_tagged_v3.ps1 -IncludeBrainTests -GuardianTag guardian_final_version -LiveGeminiGraph
```

The local run evidence is in `brain/.artifacts/tagged-v3/20261103T195333189Z-06bebe94/`; it is ignored and contains locally generated test keys. Do not publish that directory or any `.env` file.
