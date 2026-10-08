from civis_brain.contracts import DetectionResult, Node, Plan, PlanningContext, ReadingsBatch
from civis_brain.ports import PlanProvider
from civis_brain.scenarios.water.detector import detect_high_water
from civis_brain.scenarios.water.planner import plan_response


class WaterScenario:
    scenario_id = "S02"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        return detect_high_water(batch, nodes, policy, state)

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan:
        return await plan_response(context, provider)