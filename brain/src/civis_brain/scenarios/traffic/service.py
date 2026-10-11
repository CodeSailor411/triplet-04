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
from civis_brain.errors import BrainError
from civis_brain.planning.service import validate_command
from civis_brain.ports import PlanProvider


class TrafficScenario:
    scenario_id = "S01"
    _STATE_KEY = "s01_traffic"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        sensor = policy.get("sensor", "congestion_index")
        unit = policy.get("unit", "percent")
        threshold = policy.get("threshold_min")
        persistence = policy.get("persistence_ticks")

        if (
            not isinstance(threshold, (int, float))
            or isinstance(threshold, bool)
            or not isfinite(threshold)
            or not 0 <= threshold <= 100
            or not isinstance(persistence, int)
            or isinstance(persistence, bool)
            or not 1 <= persistence <= 100
            or sensor != "congestion_index"
            or unit != "percent"
        ):
            raise ValueError("Invalid traffic detection policy")

        node_by_id = {node.node_id: node for node in nodes}

        tracker = state.get(self._STATE_KEY)
        if not isinstance(tracker, dict) or tracker.get("run_id") != batch.run_id:
            tracker = {"run_id": batch.run_id, "nodes": {}}
            state[self._STATE_KEY] = tracker

        node_states: dict[str, dict[str, Any]] = tracker["nodes"]
        observations: list[Observation] = []
        incidents: list[Incident] = []
        warnings: list[str] = []
        current_readings: dict[str, tuple[Any, str | None]] = {}

        for reading in batch.readings:
            node = node_by_id.get(reading.node_id)
            domains = list(node.domains) if node else []
            reason = None

            if reading.run_id != batch.run_id or reading.tick != batch.tick:
                reason = "reading_batch_mismatch"
            elif node is None:
                reason = "unknown_node"
            elif "traffic" not in node.domains:
                reason = "node_not_in_traffic_domain"
            elif reading.sensor != sensor:
                reason = "unsupported_sensor"
            elif reading.unit != unit:
                reason = "unsupported_unit"
            elif reading.channel is not None:
                reason = "unsupported_channel"
            elif reading.value is not None and not 0 <= reading.value <= 100:
                reason = "invalid_percentage"
            elif reading.value is None:
                reason = "missing_value"

            observations.append(
                Observation(
                    reading=reading,
                    domains=domains,
                    usable=reason is None,
                    reason=reason,
                )
            )

            if (
                node is not None
                and "traffic" in node.domains
                and reading.sensor == sensor
                and reading.run_id == batch.run_id
                and reading.tick == batch.tick
            ):
                if reading.node_id in current_readings:
                    current_readings[reading.node_id] = (reading, "ambiguous_readings")
                else:
                    current_readings[reading.node_id] = (reading, reason)

        if not current_readings and any(
            "traffic" in row.domains for row in observations
        ):
            warnings.append(
                "S01: congestion_index unavailable; no agreed conversion from vehicle_count or avg_speed."
            )

        for node_id, (reading, reason) in current_readings.items():
            previous = node_states.get(node_id, {})
            last_tick = previous.get("last_tick")

            # Repeated evaluation of the same tick must not advance persistence.
            if last_tick is not None and last_tick >= batch.tick:
                continue

            above_threshold = (
                reason is None
                and isinstance(reading.value, (int, float))
                and not isinstance(reading.value, bool)
                and reading.value >= threshold
            )

            consecutive = (
                last_tick is not None
                and batch.tick == last_tick + 1
            )

            streak = (
                previous.get("streak", 0) + 1
                if above_threshold and consecutive
                else 1 if above_threshold else 0
            )

            source_ids = []
            if above_threshold:
                source_ids = list(previous.get("evidence", [])) if consecutive else []
                source_ids.append(reading.reading_id)
                source_ids = source_ids[-persistence:]
            node_states[node_id] = {
                "last_tick": batch.tick,
                "streak": min(streak, persistence),
                "evidence": source_ids,
            }
            if len(source_ids) < persistence:
                continue

            incidents.append(
                Incident(
                    incident_id=(
                        f"S01-congestion-{batch.run_id}-{node_id}-{batch.tick}"
                    ),
                    kind="congestion",
                    run_id=batch.run_id,
                    domains=list(node_by_id[node_id].domains),
                    node_ids=[node_id],
                    source_reading_ids=source_ids,
                    facts={
                        "sensor": sensor,
                        "value": reading.value,
                        "unit": unit,
                        "threshold_min": threshold,
                        "persistence_ticks": persistence,
                        "consecutive_ticks": streak,
                    },
                )
            )

        return DetectionResult(
            observations=observations,
            incidents=incidents,
            warnings=warnings,
        )

    async def draft_plan(
        self, context: PlanningContext, provider: PlanProvider
    ) -> Plan:
        traffic_nodes = {
            node.node_id: node
            for node in context.nodes
            if "traffic" in node.domains
        }

        available_readings = {
            reading.reading_id: reading
            for reading in context.evidence_readings
        }

        candidates = [
            incident
            for incident in context.incidents
            if incident.kind == "congestion"
            and "traffic" in incident.domains
            and incident.node_ids
            and all(
                node_id in traffic_nodes
                for node_id in incident.node_ids
            )
            and incident.source_reading_ids
            and all(
                reading_id in available_readings
                for reading_id in incident.source_reading_ids
            )
        ]

        if not candidates:
            return Plan(proposals=[], alerts=[])

        incident_reading_ids = {
            reading_id
            for incident in candidates
            for reading_id in incident.source_reading_ids
        }

        actions = []
        for action in context.actions:
            if (
                action.action != "set_signal_plan"
                or action.domain != "traffic"
                or action.risk != "R1"
            ):
                continue

            targets = [
                node_id
                for node_id in action.target_nodes
                if node_id in traffic_nodes
                and any(node_id in incident.node_ids or any(
                    node_id in traffic_nodes[location].neighbours
                    for location in incident.node_ids
                ) for incident in candidates)
            ]

            if targets:
                actions.append(
                    action.model_copy(update={"target_nodes": targets})
                )

        if not actions:
            return Plan(proposals=[], alerts=[])

        allowed_targets = {
            target
            for action in actions
            for target in action.target_nodes
        }

        relevant_node_ids = {
            node_id
            for incident in candidates
            for node_id in incident.node_ids
        } | allowed_targets

        evidence_readings = [
            reading
            for reading in context.evidence_readings
            if reading.reading_id in incident_reading_ids
        ]

        batch_readings = [
            reading
            for reading in context.batch.readings
            if reading.reading_id in incident_reading_ids
        ]

        visible_ids = {
            reading.reading_id
            for reading in [*evidence_readings, *batch_readings]
        }

        if not incident_reading_ids.issubset(visible_ids):
            return Plan(proposals=[], alerts=[])

        restricted_batch = context.batch.model_copy(
            update={
                "readings": batch_readings,
                "count": len(batch_readings),
            }
        )

        restricted_context = context.model_copy(
            update={
                "batch": restricted_batch,
                "incidents": candidates,
                "nodes": [
                    node
                    for node in context.nodes
                    if node.node_id in relevant_node_ids
                ],
                "actions": actions,
                "evidence_readings": evidence_readings,
            }
        )

        # Call the provider exactly once for a supported candidate.
        plan = await provider.generate(restricted_context)

        # Reject proposals that do not match the advertised action.
        for proposal in plan.proposals:
            action = next(
                (
                    item
                    for item in actions
                    if item.action == proposal.action
                ),
                None,
            )

            if action is None:
                return Plan(
                    proposals=[],
                    alerts=[*plan.alerts, "Rejected unsupported proposal."],
                )

            if (
                not proposal.targets
                or any(
                    target not in action.target_nodes
                    for target in proposal.targets
                )
                or proposal.risk != "R1"
                or proposal.preview_required != action.preview_required
                or not proposal.source_reading_ids
                or any(
                    reading_id not in incident_reading_ids
                    for reading_id in proposal.source_reading_ids
                )
            ):
                return Plan(
                    proposals=[],
                    alerts=[*plan.alerts, "Rejected unsupported proposal."],
                )

            if (len(set(proposal.source_reading_ids)) != len(proposal.source_reading_ids)
                    or not any(set(incident.source_reading_ids).issubset(
                        proposal.source_reading_ids) for incident in candidates)):
                return Plan(proposals=[], alerts=[*plan.alerts, "Rejected unsupported proposal."])
            try:
                validate_command(action, proposal.targets, proposal.params, restricted_context.nodes)
            except BrainError:
                return Plan(proposals=[], alerts=[*plan.alerts, "Rejected unsupported proposal."])

        return plan
