from civis_brain.contracts import DetectionResult, Node, Plan, PlanningContext, ReadingsBatch
from civis_brain.ports import PlanProvider
from civis_brain.scenarios.common import candidate, observations, reset_state


class PowerScenario:
    scenario_id = "S03"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        reset_state(state, batch.run_id)
        rows = observations(batch, nodes, {"load_kw": "kW", "voltage_v": "V"})
        relevant = [row for row in rows if "power" in row.domains]
        incidents = []
        warnings = []
        thresholds = policy.get("thresholds") or {}
        enabled = policy.get("threshold_detection_enabled", False)
        for row in relevant:
            if not row.usable:
                warnings.append("POWER_EVIDENCE_INVALID: missing value or wrong unit")
                continue
            threshold = thresholds.get(row.reading.sensor)
            if enabled and threshold is not None and row.reading.value >= threshold:
                incidents.append(
                    candidate(
                        "power_fault",
                        row,
                        [row.reading.reading_id],
                        {
                            "classification": (
                                "mock overload candidate, not confirmed service loss"
                                if row.reading.sensor == "load_kw"
                                else "mock voltage threshold candidate, not confirmed service loss"
                            ),
                            "threshold_is_fixture_only": policy.get("fixture_only", False),
                        },
                    )
                )
        if relevant and not incidents:
            warnings.append(
                "POWER_EVIDENCE_UNCONFIRMED: no agreed fault threshold or corroborated "
                "service-loss evidence. Low load alone does not establish an outage; "
                "grid switching is withheld."
            )
        return DetectionResult(observations=rows, incidents=incidents, warnings=warnings)

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan:
        return Plan(
            proposals=[],
            alerts=[
                f"Reported Power candidate at {', '.join(incident.node_ids)}. "
                "Grid switching is withheld: confirmed fault, safe topology and preview "
                "are not established in this reduced mock."
                for incident in context.incidents
                if incident.kind == "power_fault"
            ],
        )
