from math import isfinite
from typing import Any

from civis_brain.contracts import (
    DetectionResult,
    Incident,
    Node,
    Observation,
    Plan,
    PlanningContext,
    ReadingsBatch,
)
from civis_brain.planning.dispatch import MEDICAL, draft_dispatch
from civis_brain.ports import PlanProvider


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
            and 1 <= persistence_ticks <= 100
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
                elif reason is None and reading.channel != "ambulance":
                    reason = "units_free is not the ambulance channel"
                elif reason is None and not reading.value.is_integer():
                    reason = "units_free must be a whole count"

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
            state["_s05_last_tick"] = -1

        if batch.tick < state.get("_s05_last_tick", -1):
            return DetectionResult(observations=observations, incidents=[],
                                   warnings=["S05 stale tick ignored"])
        state["_s05_last_tick"] = batch.tick

        events_by_node: dict[str, dict[str, Any]] = state.setdefault(events_state_key, {})
        for node_id, event_state in events_by_node.items():
            if node_id not in event_readings_by_node and batch.tick > event_state["last_tick"]:
                event_state.update(last_tick=batch.tick, streak=0, reading_ids=[], history=[])

        for node_id, readings in event_readings_by_node.items():
            event_state = events_by_node.get(node_id)
            if event_state is None:
                events_by_node[node_id] = {
                    "last_tick": batch.tick,
                    "streak": 1,
                    "reading_ids": [reading.reading_id for reading in readings],
                    "history": [[reading.reading_id for reading in readings]],
                }
            elif batch.tick == event_state["last_tick"]:
                continue
            elif batch.tick == event_state["last_tick"] + 1 and event_state["streak"] > 0:
                history = [*event_state["history"],
                           [reading.reading_id for reading in readings]][-persistence_ticks:]
                event_state.update(
                    last_tick=batch.tick,
                    streak=min(event_state["streak"] + 1, persistence_ticks),
                    history=history,
                    reading_ids=[reading_id for group in history for reading_id in group],
                )
            else:
                event_state.update(
                    last_tick=batch.tick,
                    streak=1,
                    reading_ids=[reading.reading_id for reading in readings],
                    history=[[reading.reading_id for reading in readings]],
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
        return await draft_dispatch(context, provider, profile=MEDICAL)
