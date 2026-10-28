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

28 October review: PR 27, branch `codex/yassine-s06-test-hardening`, head `95154e4`, is integrated into `codex/civis-elyes`. Shared-file conflicts were resolved by retaining the current Elyes runtime, registry and debug code. Your new tests and submitted progress record are preserved. The submitted accident tests and current Traffic/shared-helper tests passed together: 55 checks. This does not complete the S06 response.

Your detector is already integrated. The shared helper and S06 dispatch routing are published on the Elyes branch. The carrier remains a discovered Emergency node advertising dispatch; the destination can be the reported Traffic node. Your current `draft_plan` still returns only an alert. Finish the fixture response using the helper below; live activation is a separate gate.

Do not replace the current shared runtime with PR 27's older copy. Its S06 early-alert shortcut bypassed the shared trust/planning path, and `ACTION_BY_SCENARIO["S06"] = None` removed dispatch routing. Those shared-file changes were excluded from integration.

## Update your branch

From your repository root, commit your own current Traffic changes first. Then:

```powershell
git switch codex/yassine-s06-test-hardening
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

Finish your response and fixtures inside the assigned Traffic paths. Open the next response PR against `codex/civis-elyes`; PR 27's submitted history is already included. Keep the existing S01 tests passing. Keep live S06 disabled until Twin confirms the individual accident-report convention and Guardian supports the required report/resource evidence.
