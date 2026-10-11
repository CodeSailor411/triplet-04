
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
from civis_brain.ports import PlanProvider


class TrafficScenario:
    scenario_id = "S01"
    _STATE_KEY = "s01_traffic"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        sensor = policy.get("sensor", "congestion_index")
        unit = policy.get("unit", "percent")
        threshold = policy.get("threshold_min", 80.0)
        persistence = policy.get("persistence_ticks", 2)

        if (
            not isinstance(threshold, (int, float))
            or isinstance(threshold, bool)
            or not isinstance(persistence, int)
            or isinstance(persistence, bool)
            or persistence < 1
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
                current_readings.setdefault(reading.node_id, (reading, reason))

        for node_id, (reading, reason) in current_readings.items():
            previous = node_states.get(node_id, {})
            last_tick = previous.get("last_tick")

            # Repeated evaluation of the same tick must not advance persistence.
            if last_tick == batch.tick:
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

            node_states[node_id] = {
                "last_tick": batch.tick,
                "last_reading_id": reading.reading_id,
                "streak": streak,
                "incident_emitted": (
                    previous.get("incident_emitted", False)
                    if above_threshold and consecutive
                    else False
                ),
            }

            if streak < persistence or node_states[node_id]["incident_emitted"]:
                continue

            previous_reading_id = previous.get("last_reading_id")
            source_ids = (
                [previous_reading_id, reading.reading_id]
                if consecutive and previous_reading_id
                else [reading.reading_id]
            )

            incidents.append(
                Incident(
                    incident_id=(
                        f"S01-congestion-{batch.run_id}-{node_id}-{batch.tick}"
                    ),
                    kind="congestion",
                    run_id=batch.run_id,
                    domains=["traffic"],
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
            node_states[node_id]["incident_emitted"] = True

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
            for reading in [
                *context.evidence_readings,
                *context.batch.readings,
            ]
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

            specs = {
                spec["name"]: spec
                for spec in action.params
                if isinstance(spec, dict)
                and isinstance(spec.get("name"), str)
            }

            for name, value in proposal.params.items():
                spec = specs.get(name)

                if spec is None:
                    return Plan(
                        proposals=[],
                        alerts=[*plan.alerts, "Rejected unsupported proposal."],
                    )

                if "choices" in spec and value not in spec["choices"]:
                    return Plan(
                        proposals=[],
                        alerts=[*plan.alerts, "Rejected unsupported proposal."],
                    )

                param_type = spec.get("type")

                if param_type == "string":
                    valid_type = isinstance(value, str)
                elif param_type == "boolean":
                    valid_type = isinstance(value, bool)
                elif param_type == "integer":
                    valid_type = (
                        isinstance(value, int) and not isinstance(value, bool)
                    )
                elif param_type == "number":
                    valid_type = (
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                    )
                else:
                    valid_type = False

                if not valid_type:
                    return Plan(
                        proposals=[],
                        alerts=[*plan.alerts, "Rejected unsupported proposal."],
                    )

                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if "min_value" in spec and value < spec["min_value"]:
                        return Plan(
                            proposals=[],
                            alerts=[*plan.alerts, "Rejected unsupported proposal."],
                        )

                    if "max_value" in spec and value > spec["max_value"]:
                        return Plan(
                            proposals=[],
                            alerts=[*plan.alerts, "Rejected unsupported proposal."],
                        )

            forbidden_terms = (
                "containment",
                "quarantine",
                "isolate_device",
                "release_device",
            )

            if any(term in proposal.reason.lower() for term in forbidden_terms):
                return Plan(
                    proposals=[],
                    alerts=[*plan.alerts, "Rejected unsupported proposal."],
                )

        return plan