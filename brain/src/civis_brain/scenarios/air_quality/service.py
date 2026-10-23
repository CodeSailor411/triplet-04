import math

from civis_brain.contracts import DetectionResult, Node, Plan, PlanningContext, ReadingsBatch
from civis_brain.ports import PlanProvider
from civis_brain.scenarios.common import candidate, observations, persistence, reset_state


class AirQualityScenario:
    scenario_id = "S04"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        if (
            policy.get("unit") != "ug/m3"
            or type(policy.get("threshold_min")) not in (int, float)
            or not math.isfinite(policy["threshold_min"])
            or policy["threshold_min"] < 0
            or type(policy.get("persistence_ticks")) is not int
            or not 2 <= policy["persistence_ticks"] <= 60
        ):
            raise ValueError("AQ policy requires ug/m3, a finite threshold and at least two ticks")
        reset_state(state, batch.run_id)
        rows = observations(batch, nodes, {"pm25": policy["unit"]})
        incidents = []
        warnings = []
        for row in rows:
            if "air_quality" not in row.domains:
                continue
            evidence = persistence(row, policy, state)
            if not row.usable:
                warnings.append("AIR_EVIDENCE_INVALID: missing value or wrong PM2.5 unit")
            if evidence:
                incidents.append(
                    candidate(
                        "air_pollution",
                        row,
                        evidence,
                        {
                            "reported_pm25": row.reading.value,
                            "persistence_ticks": policy["persistence_ticks"],
                            "threshold_is_fixture_only": policy.get("fixture_only", False),
                        },
                    )
                )
        return DetectionResult(observations=rows, incidents=incidents, warnings=warnings)

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan:
        return Plan(
            proposals=[],
            alerts=[
                f"Sustained reported air pollution at {', '.join(incident.node_ids)}. "
                "No Air Quality actuator; no corroborated emergency dispatch."
                for incident in context.incidents
                if incident.kind == "air_pollution"
            ],
        )
