# S07 Water integration handoff

24 October 2026. Owner: Elyes. S07 implementation pending receipt from Mariem.

## Confirmed inputs

- Twin declares `water_level` in **cm** and `set_valve_position.position` in **0 to 100 percent** (`twin/config/twin.yaml`). A 50% command is `50`, not `0.5`. Brain must continue validating against the live advertised manifest.
- `WAT-01` is a node identifier, not proof that it is a reservoir or supply node. Twin's inspected configuration does not establish the reservoir roles, local water-level datum, hydraulic connections or supply-preserving valve directions needed for S07.
- Dali must identify the supply nodes, datum/reference for each relevant level, controlled valves and reviewed directions. CIVIS must then configure and test the corresponding low-water thresholds and recovery conditions. Do not infer pipe connectivity from geographic neighbours.
- Keep live `supply_nodes` and reviewed valve choices empty until this metadata is confirmed. Missing metadata must prevent unsupported supply-failure conclusions and valve actuation.
- Keep synthetic `tank-01` and `valve-01` fixtures if their manifest explicitly distinguishes the observed supply node from the controlled valve. Use the shared Reading shape, cm, percent valve positions and clearly labelled fixture-only policies. Synthetic IDs do not need to become real Twin IDs.
- Do not add a new `Reading.datum` wire field unilaterally. First agree static per-node/device datum metadata and thresholds using that reference. A wire-schema change needs joint agreement if static metadata is insufficient.

## Shared code status

The runtime now passes the originating scenario ID through execution checks instead of identifying it from the actuator name. Two scenarios sharing `set_valve_position` must not select each other's policy. The shared synthetic Water helper now uses position 50 and range 0 to 100%.

Validation: 361 Brain tests pass and Ruff passes. Four new regressions cover policy selection before and after Guardian approval, with both withdrawn and still-supported evidence. These are local fixture tests, not verification of Mariem's undelivered S07 code or live three-layer interoperability.

S07 is **not registered or certified yet**. On receipt of Mariem's code, Elyes must:

1. Inspect the actual `LowWaterScenario` module and policy fields, then register it in `SCENARIOS`, `IMPLEMENTED_SCENARIOS`, runtime relevance/action mappings and policy loading.
2. Implement and test low-threshold revalidation and recovery, keeping S02 high-water behavior separate. Existing high-threshold logic alone is insufficient for S07.
3. Reuse preview, R3 trust, exact Guardian authorization, idempotency and topology checks. Test distinct sensor/valve nodes and missing topology.
4. Enable the required workflow tests and run both Water scenarios plus the full Brain suite. Mariem's reported 75 local passes have not been independently reproduced; skipped workflows do not establish integration.

## Delivering Mariem's work

GitHub currently grants `mariem-chaouachi` write access. The remote `codex/civis-meriem` branch remains at `6f294b8`; reported local commit `91589c0` was not available after fetching. A failed push does not erase local commits. The exact cause of her 403 is not yet known.

On her computer, from the repository root:

```powershell
git status --short --branch
git log -3 --oneline
git remote -v
gh auth status
```

Confirm branch `codex/civis-meriem`, repository `CodeSailor411/triplet-04` and her own GitHub account. Do not share tokens or `.env`. If her work is uncommitted, stage only her Water files, inspect the staged diff and commit them. If already committed, do not make a duplicate commit. Then push her branch. If the 403 persists, send the error text without credentials so Elyes can distinguish authentication from permission or repository-rule failures.

For a patch alternative, after committing her Water work:

```powershell
git format-patch brain-mock-2..HEAD -o s07-patches
```

Review the generated patches for secrets and unrelated changes before sharing. This captures committed work only. Once Elyes receives it, he can integrate the real module without requiring her to modify shared runtime files.

## Dependencies

Use the committed `requirements-lock.txt` and existing setup script. Do not add an independently generated `uv.lock` or upgrade dependencies for S07. A packaging migration belongs to Elyes and requires a consistent project-wide change.
