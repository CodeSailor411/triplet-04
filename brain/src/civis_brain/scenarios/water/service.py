from civis_brain.contracts import DetectionResult, Node, Plan, PlanningContext, ReadingsBatch
from civis_brain.ports import PlanProvider


class WaterScenario:
    scenario_id = "S02"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        raise NotImplementedError("Meriem: S02 detection; see docs/mock-team/MERIEM.md")

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan:
        raise NotImplementedError("Meriem: S02 response; see docs/mock-team/MERIEM.md")
