# Elyes shared-core handover

25 October 2026. Branch `codex/civis-elyes`. Development checkpoint, not a final release.

## Implemented

- Integrated the submitted heads locally: Yassine PR 17 (`7347c8f`), Maram PR 19 (`8504ac6`), Mariem PR 20 (`726c4c9`). No merge conflicts. Member commits are preserved.
- Registered S06 detection/alert, S07 low-water response and S08 detection. S08 response remains explicitly incomplete. S06 and S08 live report conventions default to disabled; S07 live supply policy also defaults to disabled while supply metadata is missing.
- S07 policy loading, strict low-threshold revalidation, recovery hysteresis, R3 preview/approval, source IDs and incident-specific supply-preserving choices now use the shared pipeline. S02/S07 policies are checked for incompatible bands at construction when both are enabled. Required S07 workflow tests run without skips.
- Extracted Medical planning into one common dispatch helper for the supported Medical, Fire and Accident unit types. Unit type, carrier, destination, one-unit quantity, availability and evidence are checked before planning and again in shared plan validation. The Medical module delegates to that helper.
- Shared execution prevents two incidents spending the same availability observation twice. An uncertain/pending dispatch keeps its reservation. A later authoritative availability observation can refresh a pool after a confirmed commit; a fresh report alone cannot release a pending allocation. Twin still enforces its own state/caps.
- Added a dependency-free geographic graph from existing discovery. It retains shared assets once, valid zero coordinates, versioned node context, original evidence IDs and ticks. Distances are metres, using great-circle reference geometry. Missing coordinates stay unknown. No road, pipe, electrical or causal edge is inferred.
- Graph context is attached only after Guardian trust checks. Containment and feed discontinuities invalidate retained context. The dispatch helper ranks already-eligible carriers by reference distance when available; this does not establish road reachability. Air Quality can explain nearby reference assets without claiming spread or affected people.
- Added Guardian v3 MCP adaptation: `describe_capabilities`, individual fresh `get_trust_verdict`, and exact `authorize_action`. It reads published inclusive cutoffs and forwards the original Guardian token. `g1` claim checks bind action, targets, params, run, time, risk, source IDs and idempotency key. Brain holds no signing key in its implementation. Twin verifies signatures and consumes tokens.
- Added S07 base/refusal replays and geographic context to the existing plain debug page. No new public MCP tool or HTTP endpoint was introduced.

## Shared helper contract for Maram and Yassine

```python
from civis_brain.planning.dispatch import DispatchProfile, draft_dispatch

plan = await draft_dispatch(context, provider, profile=DispatchProfile(
    kind="fire",
    unit_type="fire",
    report_sensor=confirmed_report_sensor,
    report_channel=confirmed_report_channel,
    report_unit=confirmed_report_unit,
    availability_fact="firefighter_available_by_carrier",
    confirmed_report=True,
))
```

The `context` must contain an independently supported incident, its destination and exact evidence. Fire's availability readings must be `units_free`, channel `fire`, unit `units`. The helper checks the actual advertised dispatch manifest. `confirmed_report=True` accepts the explicit fixture confirmation value 1; it must not be applied to aggregate call rates as though they were an individual report. Missing eligibility produces no proposal or provider call. Do not add peer calls to scenario modules.

Medical remains one ambulance. Fire is one `fire` unit. The Accident helper supports one police unit only when the member supplies the reviewed report and response convention; it does not infer injuries or dispatch an ambulance from congestion alone.

## Review and remaining member work

| Submission | Findings | Next action |
|---|---|---|
| Mariem, PR 20 | Real shared blockers: registry/routing, action-kind validation and low-direction revalidation/recovery. Those are fixed. Synthetic positive/refusal workflows now execute. Datum is policy metadata, not a verified reading field. | Keep synthetic fixtures; obtain reviewed live supply-node IDs, datum, thresholds and supply-preserving valve choices from Dali before enabling live S07. No independent `uv.lock`. |
| Maram, PR 19 | Detection and fixtures are delivered; `draft_plan` is still empty. Zero/negative/non-confirmation values could create a fire incident; that defect is fixed. Provisional unit/channel placeholders remain in her submission. Repeated-report fixture changes the tick/time under the same reading ID, which shared input validation rejects. | Use the shared helper, change resource unit/channel placeholders to Twin's actual `fire`, and agree report/event semantics. Preserve unique reading IDs and a separate stable event identity. Do not weaken `READING_ID_CONFLICT`. Re-target the PR from `main` to `codex/civis-elyes` before remote integration. |
| Yassine, PR 17 | Current diff adds S06 detection and tests; PR title/body still describe S01 and an absent runtime. Runtime exists. S06's `road_accident_report` convention is proposed and not published by Twin. It currently returns an explained alert, no dispatch. | Update the PR description and provide the agreed event convention before adding a response. Reuse the dispatch helper rather than duplicating it. |

S08 shared helper positive/refusal paths are tested with an explicitly labelled test wrapper around the real detector. That does not make the submitted empty member planner complete. A graph or GNN cannot fill missing incident evidence or partner safety metadata.

## Remaining Elyes work and joint decisions

1. Finish S08/S06 response integration after receiving the member planner and an agreed event identity/report convention. Unknown extra JSON fields are still ignored by `Reading`; adding `event_id` to a fixture alone does not implement event support.
2. Finish safe Power switching only after a reviewed grid risk tier, fault criteria, essential-service dependencies and safe switch choices are available. Twin mock 3 advertises a grid risk of null and Guardian explicitly refuses grid/R3 preview authorization. The current Power alert path remains supported; safe grid switching is not complete.
3. Get reviewed Water topology and datum metadata. Geographic neighbours cannot establish supply-preserving directions.
4. Re-run actual joint acceptance after partner fixes. The optional GNN remains a separate shadow experiment, pending training data; no learned actuation is enabled.

## Validation and use

See `PR_REVIEW_AND_V3_ACCEPTANCE_2026-10-25.md` for counts and actual partner blockers. Fixture success does not establish three-layer acceptance. Live Gemini was not called in this change; provider serialization was tested with recorded responses.

Run local Brain checks from `brain/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Run exact tagged partner checks from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/test_tagged_v3.ps1
```

The partner script intentionally returns a nonzero exit while required acceptance assertions fail. It extracts tags into ignored `.interop/oct25/`, creates an isolated combined environment and temporary test keys, and leaves partner source unchanged. The service dependency lock is unchanged. Completed environment files and signing material remain private.

For a future live v3 run, merge `config/guardian-v3.env.example` into a local configuration containing the existing role credentials and Gemini key. Guardian itself must ingest the Twin feed; Brain does not impersonate its ingestion caller or create verdicts. Preflight checks connection prerequisites, not full acceptance.
