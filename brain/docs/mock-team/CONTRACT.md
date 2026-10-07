# Frozen contract: five scenario modules and one Brain runtime

Revision: scenario ownership, 7 October 2026. Owner: Elyes. This replaces the earlier three-module team assignment. Public MCP models remain unchanged. Internal module boundaries are prepared for implementation, not implemented.

## Pipeline

~~~text
Twin batch + node/action discovery
  -> shared normalization (Elyes)
  -> five scenario detectors, separate state per scenario/run
  -> shared Guardian evidence checks (Elyes)
  -> scenario response using injected PlanProvider when applicable
  -> shared deterministic plan validation (Elyes)
  -> required safe preview + Guardian exact-action token
  -> Twin actuate, optional confirmation
  -> saved decisions and redacted trace
~~~

One MCP server and one shared provider serve all modules. Shared nodes retain all domains. A mixed batch may produce incidents in more than one scenario; do not make a global single-domain choice. For the primary demos, each fixture selects one scenario; shared code must route relevant context without generating unrelated actions.

## Fixed Python interfaces

Types are in civis_brain.contracts, ports in civis_brain.ports. Only Elyes changes them. Each scenario class implements:

~~~python
scenario_id: str

def detect(self, batch: ReadingsBatch, nodes: list[Node],
           policy: dict, state: dict) -> DetectionResult: ...

async def draft_plan(self, context: PlanningContext,
                     provider: PlanProvider) -> Plan: ...
~~~

| ID | Class | Source module |
| --- | --- | --- |
| S01 | TrafficScenario | scenarios/traffic/service.py |
| S02 | WaterScenario | scenarios/water/service.py |
| S03 | PowerScenario | scenarios/power/service.py |
| S04 | AirQualityScenario | scenarios/air_quality/service.py |
| S05 | EmergencyScenario | scenarios/emergency/service.py |

scenarios/registry.py holds exactly these five explicit entries in this order. It is leader-owned. No plugin auto-discovery or dynamic code loading. IncidentKind retains eight values for peer compatibility; this registry implements only five selected workflows.

- normalize_batch(batch, nodes) -> ReadingsBatch validates count/run/tick/time/node semantics before detection. Reject malformed batch with ValueError; no downstream actuation. Preserve null, explicit units, timestamps and source IDs.
- A detector uses only its declared sensor/unit/channel. Unknown or missing values never become zero. Observations are candidate data, not Guardian-approved facts.
- Shared runtime retains a bounded per-run reading ledger. PlanningContext.evidence_readings contains the selected original readings, including earlier persistence ticks; context.batch remains the current wire batch. Validate proposal source IDs against this supplied evidence and the ledger, not current tick alone. A field with a missing historical source ID cannot authorize a request.
- state belongs to one scenario and one run. Preserve persistence between ticks, reset on run change, and do not extend streaks on duplicate ticks. No module-global mutable history.
- draft_plan receives only its relevant incidents, selected evidence and restricted action manifest. It cannot assess trust, mint tokens, preview, execute or perform containment.
- With no incident, return an empty Plan without a provider call. AQ and reduced Power return alerts/blocked-reason inputs without a provider call. Actionable S01/S02/S05 may call only await provider.generate(context) once per attempt under the shared call budget. The shared live provider serializes selected evidence/incident facts and allowed actions; raw untrusted batch values are not an alternate source of facts.
- Per-scenario checks constrain the response to its scenario. Final validation remains in shared planning.service.validate_plan(context, plan) -> Plan; it checks actual manifest/evidence, not the AI's own claims.
- PlanProvider.generate(context) -> Plan is shared: Elyes implements live Gemini and recorded fixtures. Tests may define a small fake provider only in their own test folder.
- ToolPeer.call_tool(name, arguments) -> dict is shared: Elyes implements live MCP and reusable fixture peers. Members never create another live partner stack.

## Fixed workflow test harness

integration/runtime.py reserves the following interface for Elyes:

~~~python
runtime = build_runtime(
    twin=fixture_twin, guardian=fixture_guardian, provider=fixture_provider,
    policies=all_five_policies, features=fixture_features,
    artifact_dir=temporary_trace_directory,
)
result: DecisionBatch = await runtime.evaluate_tick(batch)
~~~

The factory and method currently raise NotImplementedError. policies maps all five IDs to per-scenario config dictionaries. features uses the explicit internal schema in SCENARIOS.md for discovery/fixture options; it is not permission to bypass validation. Planned fixture constructors are FixtureTwin(case: dict), FixtureGuardian(case: dict) and FixturePlanProvider(case: dict), implemented by Elyes. Peer fixtures expose calls as a list of records with name and redacted arguments, and effects as a list of committed normalized commands without tokens. Fixtures record tool calls and simulated effects. Only Elyes fixes the shared harness if a member finds a missing contract.

The existing module-level integration.service.evaluate_tick(batch) and MCP tool signature remain stable; Elyes binds one runtime at startup and delegates to it. Runtime constructor/factory details must not be guessed independently in member tests.

## Partner wire contract

Basis: final decision report and unmerged Twin twin-containment at 40a7c90, inspected 7 October. Partner code is evidence, not automatically an agreed amendment.

- Twin tools: get_capabilities, list_nodes, get_readings, get_clock, list_actions. Join domains from nodes; readings carry run_id, reading_id, tick, timestamp, node_id, device_id, sensor, channel, value, unit.
- Current sensors include congestion_index (planned), water_level, load_kw, voltage_v, pm25, emergency_calls and units_free. Emergency channels are numeric calls/min; no injury details or real transcripts are available yet.
- Actuation uses string action plus separate targets, params, token, idempotency_key.
- S01 action: set_signal_plan, R1. S02: set_valve_position, R3 and required preview. S05: dispatch, R2.
- Dispatch targets are carrier nodes. params.destination is the incident node; unit type ambulance and units 1 only when supported/available. The manifest determines exact parameter names and bounds.
- Power grid changes require preview/token/caps but are outside this reduced response implementation. AQ has no direct actuator. Only Guardian requests isolation/quarantine/rollback/release.
- Guardian scores stay numeric with declared scale/cut-offs. No score or cached verdict substitutes for its token. Tool names and token details need partner confirmation.

## Execution and failures

Shared code checks action name, parameters, carrier/location, units, source IDs, risk and required preview against discovery. Do not trust AI risk labels or instructions embedded in readings/tool descriptions. Missing usable evidence, approval or supported safe preview produces blocked behavior and zero actuation.

Guardian approves the exact normalized action/targets/params for the Twin run/clock. Brain never issues that token. Twin enforces token and caps. Cap rejection is atomic; keep its detail, do not retry unchanged or split requests to bypass it. Shared nodes count in each applicable domain. Read limits from discovery; do not copy the PDF table into production logic.

Unchanged logical command keeps its idempotency key. A changed command requires a new key and approval. An uncertain send outcome is reconciled with the original key, never blindly resent with a new one. Pending remains pending until advertised confirmation succeeds; absent commit support never becomes fabricated success.

Emit a Power unsupported-evidence warning only when relevant Power observations exist; an unrelated traffic/water/medical batch must not gain a Power alert. Warnings such as unsupported Power evidence must become an explicit saved alert/blocked decision, not disappear because there is no confirmed incident. Alert success means a recorded alert with zero actuator effects; it is not a physical-action success.

No human-review workflow. No AI or live peer calls in CI. No secrets in prompts, fixtures, logs, screenshots, commits or PRs. Clock values come from Twin; local wall time is for timeout only.

## Proposed public tools and logs

MCP at /mcp, port 8001, protocol 2026-07-28. get_capabilities is implemented; evaluate_tick, get_active_incidents, explain_decision and Guardian-only notify_containment are prepared but unimplemented. Optional set_policy_mode is deferred.

Record run, tick, scenario_id, incident/evidence IDs, status, reason and peer refusal detail in mock JSONL. Runtime assigns scenario_id to trace events; no public model change is required. Decision status is alert/blocked/pending/committed/rejected. Never save tokens/keys. Map this format to Trinity's shared log draft when confirmed.
