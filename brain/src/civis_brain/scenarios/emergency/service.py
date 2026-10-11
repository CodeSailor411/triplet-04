from math import isfinite
from typing import Any

from civis_brain.contracts import (
    ActionInfo,
    ActionProposal,
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


def _manifest_accepts_value(parameter: dict[str, Any], value: Any) -> bool:
    parameter_type = parameter.get("type")
    if parameter_type in {"string", "str"}:
        if not isinstance(value, str):
            return False
    elif parameter_type in {"integer", "int"}:
        if type(value) is not int:
            return False
    elif parameter_type in {"number", "float"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
    else:
        return False

    choices = parameter.get("choices")
    if choices is not None and (not isinstance(choices, list) or value not in choices):
        return False

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = parameter.get("min_value")
        maximum = parameter.get("max_value")
        if minimum is not None and value < minimum:
            return False
        if maximum is not None and value > maximum:
            return False
    return True


def _dispatch_manifest_supports(action: ActionInfo, destination: str) -> bool:
    required_values = {
        "unit_type": "ambulance",
        "destination": destination,
        "units": 1,
    }
    parameter_names = [parameter.get("name") for parameter in action.params]
    if (
        action.action != "dispatch"
        or action.domain != "emergency"
        or action.risk != "R2"
        or (action.action_cap is not None and action.action_cap < 1)
        or set(parameter_names) != set(required_values)
        or len(parameter_names) != len(set(parameter_names))
    ):
        return False

    parameters_by_name = {parameter["name"]: parameter for parameter in action.params}
    return all(
        _manifest_accepts_value(parameters_by_name[name], value)
        for name, value in required_values.items()
    )


def _incident_evidence(
    context: PlanningContext, incident: Incident
) -> tuple[list[str], dict[str, list[Reading]]] | None:
    if (
        incident.kind != "medical"
        or "emergency" not in incident.domains
        or incident.run_id != context.batch.run_id
        or len(incident.node_ids) != 1
        or incident.facts.get("destination") != incident.node_ids[0]
    ):
        return None

    evidence_by_id = {reading.reading_id: reading for reading in context.evidence_readings}
    if (
        len(evidence_by_id) != len(context.evidence_readings)
        or not incident.source_reading_ids
        or len(set(incident.source_reading_ids)) != len(incident.source_reading_ids)
        or not set(incident.source_reading_ids) <= evidence_by_id.keys()
    ):
        return None

    availability_facts = incident.facts.get("ambulance_available_by_carrier")
    if not isinstance(availability_facts, dict):
        return None

    call_reading_ids = []
    availability_by_carrier: dict[str, list[Reading]] = {}
    for reading_id in incident.source_reading_ids:
        reading = evidence_by_id[reading_id]
        if reading.run_id != incident.run_id:
            return None
        if reading.sensor == "emergency_calls":
            if (
                reading.node_id != incident.node_ids[0]
                or reading.channel != "medical"
                or reading.unit != "calls/min"
                or reading.value is None
                or reading.value < 0
            ):
                return None
            call_reading_ids.append(reading_id)
        elif reading.sensor == "units_free":
            reported_readings = availability_facts.get(reading.node_id)
            if (
                reading.unit != "units"
                or reading.value is None
                or reading.value < 0
                or not isinstance(reported_readings, list)
                or reading.model_dump(mode="json") not in reported_readings
            ):
                return None
            availability_by_carrier.setdefault(reading.node_id, []).append(reading)
        else:
            return None

    if not call_reading_ids:
        return None
    return call_reading_ids, availability_by_carrier


def _proposal_matches_candidate(
    proposal: ActionProposal,
    *,
    incident: Incident,
    action: ActionInfo,
    carrier_id: str,
    call_reading_ids: list[str],
    availability_reading: Reading,
) -> bool:
    expected_params = {
        "unit_type": "ambulance",
        "destination": incident.node_ids[0],
        "units": 1,
    }
    if (
        proposal.action != "dispatch"
        or proposal.risk != "R2"
        or proposal.preview_required != action.preview_required
        or proposal.targets != [carrier_id]
        or proposal.params != expected_params
        or not _dispatch_manifest_supports(action, incident.node_ids[0])
    ):
        return False

    proposal_reading_ids = proposal.source_reading_ids
    allowed_reading_ids = {*call_reading_ids, availability_reading.reading_id}
    return (
        len(set(proposal_reading_ids)) == len(proposal_reading_ids)
        and set(proposal_reading_ids) <= allowed_reading_ids
        and bool(set(proposal_reading_ids) & set(call_reading_ids))
        and availability_reading.reading_id in proposal_reading_ids
    )


class EmergencyScenario:
    scenario_id = "S05"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        node_by_id = {node.node_id: node for node in nodes}
        event_sensor = policy.get("sensor")
        event_channel = policy.get("channel")
        event_unit = policy.get("unit")
        availability_sensor = policy.get("availability_sensor")
        availability_unit = policy.get("availability_unit")
        threshold = policy.get("threshold_min")
        persistence_ticks = policy.get("persistence_ticks")

        valid_threshold = (
            isinstance(threshold, (int, float))
            and not isinstance(threshold, bool)
            and isfinite(threshold)
        )
        valid_persistence = (
            isinstance(persistence_ticks, int)
            and not isinstance(persistence_ticks, bool)
            and persistence_ticks > 0
        )

        observations: list[Observation] = []
        event_readings_by_node: dict[str, list[Any]] = {}
        availability_by_carrier: dict[str, list[Any]] = {}

        for reading in batch.readings:
            if reading.sensor not in {event_sensor, availability_sensor}:
                continue

            node = node_by_id.get(reading.node_id)
            domains = node.domains if node is not None else []
            reason = None
            if node is None:
                reason = "node is not in discovery"
            elif "emergency" not in domains:
                reason = "node is outside the emergency domain"
            elif reading.value is None:
                reason = "reading value is null"
            elif reading.value < 0:
                reason = "reading value is negative"

            if reading.sensor == event_sensor:
                if reason is None and reading.unit != event_unit:
                    reason = "unexpected emergency_calls unit"
                elif reason is None and reading.channel != event_channel:
                    reason = "unexpected emergency_calls channel"

                usable = reason is None
                observations.append(
                    Observation(
                        reading=reading,
                        domains=domains,
                        usable=usable,
                        reason=reason,
                    )
                )
                if (
                    usable
                    and valid_threshold
                    and valid_persistence
                    and reading.value >= threshold
                ):
                    event_readings_by_node.setdefault(reading.node_id, []).append(reading)
            else:
                if reason is None and reading.unit != availability_unit:
                    reason = "unexpected units_free unit"

                usable = reason is None
                observations.append(
                    Observation(
                        reading=reading,
                        domains=domains,
                        usable=usable,
                        reason=reason,
                    )
                )
                if (
                    usable
                    and node is not None
                    and "dispatch" in node.actuators
                ):
                    availability_by_carrier.setdefault(reading.node_id, []).append(reading)

        warnings = []
        if not valid_threshold or not valid_persistence:
            warnings.append("S05 event detection disabled by invalid threshold or persistence policy")

        run_state_key = "_s05_run_id"
        events_state_key = "_s05_events_by_node"
        if state.get(run_state_key) != batch.run_id:
            state[run_state_key] = batch.run_id
            state[events_state_key] = {}

        events_by_node: dict[str, dict[str, Any]] = state.setdefault(events_state_key, {})
        for node_id, event_state in events_by_node.items():
            if node_id not in event_readings_by_node and batch.tick > event_state["last_tick"]:
                event_state.update(last_tick=batch.tick, streak=0, reading_ids=[])

        for node_id, readings in event_readings_by_node.items():
            event_state = events_by_node.get(node_id)
            if event_state is None:
                events_by_node[node_id] = {
                    "last_tick": batch.tick,
                    "streak": 1,
                    "reading_ids": [reading.reading_id for reading in readings],
                }
            elif batch.tick == event_state["last_tick"]:
                continue
            elif batch.tick == event_state["last_tick"] + 1 and event_state["streak"] > 0:
                event_state.update(
                    last_tick=batch.tick,
                    streak=event_state["streak"] + 1,
                    reading_ids=[
                        *event_state["reading_ids"],
                        *(reading.reading_id for reading in readings),
                    ],
                )
            else:
                event_state.update(
                    last_tick=batch.tick,
                    streak=1,
                    reading_ids=[reading.reading_id for reading in readings],
                )

        incidents = []
        if valid_threshold and valid_persistence:
            for node_id in event_readings_by_node:
                event_state = events_by_node[node_id]
                if event_state["streak"] < persistence_ticks:
                    continue

                carrier_facts = {
                    carrier_id: [reading.model_dump(mode="json") for reading in readings]
                    for carrier_id, readings in availability_by_carrier.items()
                }
                source_reading_ids = list(
                    dict.fromkeys(
                        [
                            *event_state["reading_ids"],
                            *(
                                reading.reading_id
                                for readings in availability_by_carrier.values()
                                for reading in readings
                            ),
                        ]
                    )
                )
                node = node_by_id[node_id]
                incidents.append(
                    Incident(
                        incident_id=f"S05:{batch.run_id}:{node_id}:medical",
                        kind="medical",
                        run_id=batch.run_id,
                        domains=node.domains,
                        node_ids=[node_id],
                        source_reading_ids=source_reading_ids,
                        facts={
                            "destination": node_id,
                            "ambulance_available_by_carrier": carrier_facts,
                        },
                    )
                )

        return DetectionResult(observations=observations, incidents=incidents, warnings=warnings)

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan:
        if not context.incidents:
            return Plan(proposals=[])

        dispatch_actions = [
            action
            for action in context.actions
            if action.action == "dispatch" and action.domain == "emergency"
        ]
        if len(dispatch_actions) != 1:
            return Plan(proposals=[])
        dispatch_action = dispatch_actions[0]

        nodes_by_id = {node.node_id: node for node in context.nodes}
        candidates = []
        for incident in context.incidents:
            incident_evidence = _incident_evidence(context, incident)
            if incident_evidence is None:
                continue
            call_reading_ids, availability_by_carrier = incident_evidence
            destination_node = nodes_by_id.get(incident.node_ids[0])
            if destination_node is None or "emergency" not in destination_node.domains:
                continue

            for carrier_id in dispatch_action.target_nodes:
                carrier_node = nodes_by_id.get(carrier_id)
                available_readings = availability_by_carrier.get(carrier_id, [])
                if (
                    carrier_node is None
                    or "emergency" not in carrier_node.domains
                    or "dispatch" not in carrier_node.actuators
                    or len(available_readings) != 1
                    or available_readings[0].value is None
                    or available_readings[0].value < 1
                    or not _dispatch_manifest_supports(
                        dispatch_action, incident.node_ids[0]
                    )
                ):
                    continue
                candidates.append(
                    (
                        incident,
                        dispatch_action,
                        carrier_id,
                        call_reading_ids,
                        available_readings[0],
                    )
                )

        if not candidates:
            return Plan(proposals=[])

        generated_plan = await provider.generate(context)
        accepted_proposals = []
        planned_incident_ids = set()
        for proposal in generated_plan.proposals:
            for incident, action, carrier_id, call_reading_ids, availability_reading in candidates:
                if incident.incident_id in planned_incident_ids:
                    continue
                if _proposal_matches_candidate(
                    proposal,
                    incident=incident,
                    action=action,
                    carrier_id=carrier_id,
                    call_reading_ids=call_reading_ids,
                    availability_reading=availability_reading,
                ):
                    accepted_proposals.append(
                        proposal.model_copy(
                            update={
                                "reason": (
                                    "Dispatch one available ambulance to the reported "
                                    "medical-event location using supplied evidence."
                                )
                            }
                        )
                    )
                    planned_incident_ids.add(incident.incident_id)
                    break

        return Plan(proposals=accepted_proposals)
