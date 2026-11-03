"""Fixture-stage detector for S08 reported-fire evidence."""

from civis_brain.contracts import (
    DetectionResult,
    Incident,
    Node,
    Observation,
    Plan,
    PlanningContext,
    Reading,
    ReadingsBatch,
)
from civis_brain.ports import PlanProvider


class FireScenario:
    scenario_id = "S08"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        report_sensor = policy.get("report_sensor")
        report_channel = policy.get("report_channel")
        report_unit = policy.get("report_unit")
        unit_type = policy.get("unit_type")
        availability_sensor = policy.get("availability_sensor")
        availability_channel = policy.get("availability_channel")
        availability_unit = policy.get("availability_unit")
        required = (
            report_sensor,
            report_channel,
            report_unit,
            unit_type,
            availability_sensor,
            availability_channel,
            availability_unit,
        )
        if not all(isinstance(value, str) and value for value in required):
            return DetectionResult(
                observations=[],
                incidents=[],
                warnings=["S08 fire detection disabled by incomplete policy"],
            )

        run_key = "_s08_run_id"
        reports_key = "_s08_reports"
        if state.get(run_key) != batch.run_id:
            state.clear()
            state[run_key] = batch.run_id
            state[reports_key] = {}
            state["_s08_last_tick"] = -1

        if batch.tick < state.get("_s08_last_tick", -1):
            return DetectionResult(
                observations=[],
                incidents=[],
                warnings=["S08 stale tick ignored"],
            )
        state["_s08_last_tick"] = batch.tick

        node_by_id = {node.node_id: node for node in nodes}
        untrusted_ids = state.get("_s08_untrusted_reading_ids", ())
        if not isinstance(untrusted_ids, (set, frozenset, list, tuple)) or any(
            not isinstance(reading_id, str) for reading_id in untrusted_ids
        ):
            untrusted_ids = ()
        else:
            untrusted_ids = set(untrusted_ids)

        observations: list[Observation] = []
        reports = []
        availability_by_carrier: dict[str, list[Reading]] = {}
        seen_report_ids: set[str] = set()

        for reading in batch.readings:
            if reading.sensor not in {report_sensor, availability_sensor}:
                continue

            node = node_by_id.get(reading.node_id)
            domains = node.domains if node is not None else []
            reason = None
            if reading.reading_id in untrusted_ids:
                reason = "reading is marked untrusted"
            elif node is None:
                reason = "destination node is not in discovery"
            elif "emergency" not in domains:
                reason = "destination node is outside the emergency domain"
            elif reading.value is None:
                reason = "reading value is null"

            if reading.sensor == report_sensor:
                if reason is None and reading.value != 1:
                    reason = "report must explicitly confirm fire"
                if reason is None and reading.channel != report_channel:
                    reason = "unexpected reported-fire channel"
                elif reason is None and reading.unit != report_unit:
                    reason = "unexpected reported-fire unit"

                coordinate_pair = None
                if reason is None:
                    if reading.lat is not None and reading.lon is not None:
                        coordinate_pair = (reading.lat, reading.lon)
                    elif node is not None and node.lat is not None and node.lon is not None:
                        coordinate_pair = (node.lat, node.lon)
                    else:
                        reason = "reported-fire location has no coordinates"

                usable = reason is None
                observations.append(
                    Observation(
                        reading=reading,
                        domains=domains,
                        usable=usable,
                        reason=reason,
                    )
                )
                if usable and reading.reading_id not in seen_report_ids:
                    seen_report_ids.add(reading.reading_id)
                    reports.append((reading, node, coordinate_pair))
            else:
                if reason is None and reading.channel != availability_channel:
                    reason = "unexpected firefighter availability channel"
                elif reason is None and reading.unit != availability_unit:
                    reason = "unexpected firefighter availability unit"
                elif reason is None and (
                    reading.value is None
                    or reading.value < 0
                    or not reading.value.is_integer()
                ):
                    reason = "firefighter availability must be a non-negative whole count"

                usable = (
                    reason is None
                    and node is not None
                    and "dispatch" in node.actuators
                )
                if reason is None and not usable:
                    reason = "availability node does not advertise dispatch"
                observations.append(
                    Observation(
                        reading=reading,
                        domains=domains,
                        usable=usable,
                        reason=reason,
                    )
                )
                if usable:
                    availability_by_carrier.setdefault(reading.node_id, []).append(reading)

        reports_state = state.setdefault(reports_key, {})
        incidents = []
        for reading, node, coordinate_pair in reports:
            if node is None or coordinate_pair is None:
                continue
            identity = (
                reading.node_id,
                reading.device_id,
                reading.sensor,
                reading.channel,
                reading.unit,
                reading.value,
                coordinate_pair,
            )
            previous = reports_state.get(reading.reading_id)
            if previous is not None and previous["identity"] != identity:
                continue

            incident_id = f"S08:{batch.run_id}:{reading.reading_id}:fire"
            reports_state[reading.reading_id] = {
                "identity": identity,
                "incident_id": incident_id,
            }
            carrier_facts = {
                carrier_id: [item.model_dump(mode="json") for item in items]
                for carrier_id, items in availability_by_carrier.items()
            }
            source_reading_ids = list(
                dict.fromkeys(
                    [
                        reading.reading_id,
                        *(
                            item.reading_id
                            for items in availability_by_carrier.values()
                            for item in items
                        ),
                    ]
                )
            )
            incidents.append(
                Incident(
                    incident_id=incident_id,
                    kind="fire",
                    run_id=batch.run_id,
                    domains=node.domains,
                    node_ids=[node.node_id],
                    source_reading_ids=source_reading_ids,
                    facts={
                        "destination": node.node_id,
                        "report_reading_id": reading.reading_id,
                        "location": {
                            "node_id": node.node_id,
                            "lat": coordinate_pair[0],
                            "lon": coordinate_pair[1],
                        },
                        "firefighter_unit_type": unit_type,
                        "firefighter_available_by_carrier": carrier_facts,
                    },
                )
            )

        return DetectionResult(observations=observations, incidents=incidents)

    async def draft_plan(
        self, context: PlanningContext, provider: PlanProvider
    ) -> Plan:
        # Step 4 work: S08 plan generation is intentionally not implemented here.
        return Plan(proposals=[])
