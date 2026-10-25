# Yassine: S06 continuation

S06 uses the existing Traffic folder. Do not create a new S06 package or a second Brain server.

| Purpose | Path from repository root |
|---|---|
| Your detector and response | `brain/src/civis_brain/scenarios/traffic/accident.py` |
| Your tests | `brain/tests/scenarios/traffic/` |
| Your fixtures | `brain/mocks/cases/traffic/` |
| Your configuration | `brain/config/scenarios/traffic_accident.json` |
| Shared dispatch helper | `brain/src/civis_brain/planning/dispatch.py` |
| Shared contract example and tests | `brain/tests/integration/test_accident_dispatch_contract.py` |

Your `accident.py` is already in PR 17 and integrated into the Elyes development branch. The missing shared helper had not been pushed. Elyes also corrected a helper restriction that would have rejected a Traffic-only accident destination. The carrier remains an Emergency node that advertises dispatch; the destination can be the reported Traffic node. S06 action routing now exposes the dispatch manifest. Your submitted planner remains alert-only until you implement the response.

## Update your branch

From your repository root, commit your own current Traffic changes first. Then:

```powershell
git switch codex/civis-yassine
git fetch origin
git merge origin/codex/civis-elyes
```

If Git reports conflicts, stop and send Elyes the output. Do not reset, delete work or accept every conflict automatically. The merge updates your branch; it does not write to Elyes or main. Run the existing setup if your environment needs refreshing, then run your Traffic tests from `brain/`.

## Step 4: use the common helper

Preserve a supported incident's report IDs and `run_id`. To propose police dispatch, its facts need:

- `destination`: the reported Traffic node ID.
- `police_available_by_carrier`: each discovered eligible Emergency carrier ID mapped to its original current-tick `units_free` readings, serialized with `model_dump(mode="json")`.
- `source_reading_ids`: both the actual report IDs and the availability IDs used by the candidate. Availability uses channel `police`, unit `units`; do not invent a reading or carrier.

Use the helper from your `draft_plan` method:

```python
from civis_brain.planning.dispatch import DispatchProfile, draft_dispatch

return await draft_dispatch(context, provider, profile=DispatchProfile(
    kind="road_accident",
    unit_type="police",
    report_sensor="road_accident_report",
    report_channel=None,
    report_unit="report",
    availability_fact="police_available_by_carrier",
    confirmed_report=True,
))
```

This report convention is currently **synthetic only**. Twin's aggregate `emergency_calls` accident channel is not automatically an individual confirmed accident report. Keep live S06 disabled until the partners confirm event identity and meaning. Missing independent injury evidence means no ambulance; do not implement secondary medical dispatch from an unknown injury state.

The shared example proves police dispatch to a Traffic-only location, Guardian denial, missing availability and unsupported police dispatch in the manifest. Its test wrapper demonstrates the required contract; it is not your completed member planner. Keep peer calls, tokens and execution out of your scenario.

From `brain/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/scenarios/traffic tests/integration/test_accident_dispatch_contract.py -q
```

Finish your response and fixtures inside the assigned Traffic paths. Submit the next changes against `codex/civis-elyes` and update PR 17's stale S01/runtime description if it remains open. Keep the existing S01 tests passing.
