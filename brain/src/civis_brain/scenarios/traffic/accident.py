"""S06: fail-closed detection of explicit road-accident report readings."""

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


class RoadAccidentScenario:
    scenario_id = "S06"

    # This input convention requires confirmation by the Twin owner.
    REPORT_SENSOR = "road_accident_report"
    REPORT_UNIT = "report"

    def detect(
        self,
        batch: ReadingsBatch,
        nodes: list[Node],
        policy: dict,
        state: dict,
    ) -> DetectionResult:
        node_by_id = {node.node_id: node for node in nodes}
        observations: list[Observation] = []
        incidents: list[Incident] = []
        warnings: list[str] = []
        seen_by_run = state.setdefault("_s06_seen_report_ids_by_run", {})
        seen_report_ids = set(seen_by_run.get(batch.run_id, []))

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
            elif reading.sensor != self.REPORT_SENSOR:
                reason = "not_an_explicit_accident_report"
            elif reading.unit != self.REPORT_UNIT:
                reason = "unsupported_report_unit"
            elif reading.channel is not None:
                reason = "unsupported_report_channel"
            elif reading.value != 1:
                reason = "report_not_confirmed"

            observations.append(
                Observation(
                    reading=reading,
                    domains=domains,
                    usable=reason is None,
                    reason=reason,
                )
            )

            if reason is not None:
                continue

            # A report ID is the only identity available in the current contract.
            # Repeated delivery of the same ID must not create another incident.
            if reading.reading_id in seen_report_ids:
                continue
            seen_report_ids.add(reading.reading_id)

            incidents.append(
                Incident(
                    incident_id=f"S06-road-accident-{batch.run_id}-{reading.reading_id}",
                    kind="road_accident",
                    run_id=batch.run_id,
                    domains=["traffic"],
                    node_ids=[reading.node_id],
                    source_reading_ids=[reading.reading_id],
                    facts={
                        "report_status": "reported",
                        "injury_status": "unknown",
                        "dispatch_authorized": False,
                    },
                )
            )

        seen_by_run[batch.run_id] = sorted(seen_report_ids)[-1000:]

        if not incidents:
            warnings.append(
                "S06: no usable explicit road-accident report; no dispatch proposed."
            )

        return DetectionResult(
            observations=observations,
            incidents=incidents,
            warnings=warnings,
        )

    async def draft_plan(
        self,
        context: PlanningContext,
        provider: PlanProvider,
    ) -> Plan:
        # Fail closed until the shared contract advertises a reviewed,
        # available action and its exact parameters for road accidents.
        return Plan(
            proposals=[],
            alerts=[
                "S06: report detected, but no reviewed road-accident dispatch action is configured."
            ]
            if any(i.kind == "road_accident" for i in context.incidents)
            else [],
        )

