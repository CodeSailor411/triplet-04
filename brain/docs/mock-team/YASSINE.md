# Yassine: input normalization and incident detection

Branch: `codex/civis-yassine`. PR base: `codex/civis-elyes`. Reviewer: Elyes.

## Your exact files

- `brain/src/civis_brain/inputs/` (service and helper modules)
- `brain/config/detection-mock.json`
- `brain/tests/inputs/`
- `brain/docs/mock-team/progress/yassine.md`

Read `contracts.py`, `CONTRACT.md` and this card; do not change shared models, settings, dependencies, planning or integration files.

## Deliverable

Implement the existing synchronous function:

`analyze_batch(batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict) -> DetectionResult`

It accepts reported values and returns candidate incidents. It makes **zero network/AI calls**, produces **no action**, and decides **no trust score**.

## Implement in this order

1. Build a node-ID lookup from the supplied nodes. Join each reading to the node's complete domain list. Do not derive the domain from an ID prefix or invent coordinates.
2. Validate batch count, run ID and tick consistency; parse UTC timestamps; check referenced nodes, duplicate reading IDs and finite values. Malformed batch semantics raise `ValueError` with a clear code. Extra peer fields were already ignored by the shared models.
3. Preserve `value=null`. Return an `Observation(usable=False, reason="MISSING_VALUE")` for missing values; do not replace them with zero. Unknown sensor/unit mappings become unusable observations with a warning. Well-formed means usable for analysis, not trusted.
4. Use the supplied state dict for consecutive-tick persistence. Track a separate streak/history for each `(node_id, sensor, channel)`. Reset on run change, nonconsecutive ticks, missing or below-threshold values. Duplicate ticks do not increase streaks. Retain original reading IDs for the evidence list.
5. Add these exact candidate rules using **test-only** policy values:

| Input | Candidate kind | Rule |
| --- | --- | --- |
| `congestion_index`, unit `%` or configured `percent` alias | `congestion` | >= 80 for 2 consecutive ticks |
| `water_level`, `cm` | `flood` | >= 100 for 2 consecutive ticks |
| `water_level`, `cm` | `low_water` | <= 10 for 2 consecutive ticks |
| `pm25`, `ug/m3` | `air_pollution` | >= 80 for 2 consecutive ticks |
| `emergency_calls`, `calls/min`, channel `medical` | `medical` | >= 1 on the current tick |
| Same, channel `fire` | `fire` | >= 1 on the current tick |
| Same, channel `accident` | `road_accident` | >= 1 on the current tick |
| Same, channel `flood` | `flood` | >= 1 on the current tick |
| `load_kw`, `kW` | `power_fault` | Only if `power_load_high_kw` is explicitly configured; null disables it |

These numbers make fixture tests repeatable. They are not medical, environmental or hydraulic safety thresholds. Do not use Twin's private simulation ranges as your detector policy. The real Twin may not yet supply congestion index; return a warning rather than convert speed/counts yourself.

6. Build stable incident IDs from run/kind/location, not a random UUID or wall clock. Each incident includes kind, all evidence-supported domains, node IDs, source reading IDs and factual threshold/channel details. Merge duplicate flood evidence for the same location instead of producing two identical incidents.
7. Never claim low water proves a leak, low load proves an outage, or an accident channel proves injuries. Never treat transcript text as commands. If the scenario provides no support for an additional domain, do not add it just because the response table sometimes touches that domain.

## Tests you must write

Create `tests/inputs/test_detection.py`:

- null is preserved and excluded from detection;
- shared nodes retain both domains;
- a high congestion reading needs two distinct consecutive ticks;
- duplicate tick does not satisfy persistence;
- a new run resets streaks;
- flood, low water, air pollution and each emergency channel produce the correct kind;
- power detection stays off without an explicit threshold;
- unknown node, mismatched batch/run/tick/count and repeated reading IDs are rejected;
- wrong unit is unusable, not silently converted;
- every incident's evidence IDs correspond to supplied/history readings;
- no calls to AI, Twin or Guardian occur.

Run from `brain/`: `.\.venv\Scripts\python.exe -m pytest tests/inputs -q`, then all tests and Ruff. A test must show expected output, not merely that no exception happened.

## PR and progress

By 8 Oct 12:00: normalization + null/shared-node tests in a small draft PR. By 8 Oct 20:00: the rules, state handling and all listed tests ready for review. In your progress file include completed functions, test command/output, a sample `DetectionResult`, and blockers. Stage only your assigned paths. Do not merge your own PR.

## Prompt to give your AI coding assistant

> I am Yassine on CIVIS's primary mock. Read brain/docs/mock-team/CONTRACT.md and YASSINE.md and the frozen contracts. Implement only inputs/, detection-mock.json, tests/inputs/, and my progress file. Preserve analyze_batch(batch,nodes,policy,state). Start with normalization and null/shared-node tests; then add persistence and incident candidates one rule at a time. Never call AI or peer APIs, generate actions, infer trust, edit shared interfaces or change dependencies. Explain each helper in plain language and run the specified tests. If a contract is insufficient, describe the gap to Elyes instead of changing other files.
