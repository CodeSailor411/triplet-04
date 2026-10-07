from civis_brain.contracts import DetectionResult, Node, Plan, PlanningContext, ReadingsBatch
from civis_brain.ports import PlanProvider


class EmergencyScenario:
    scenario_id = "S05"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        raise NotImplementedError("Maram: S05 detection; see docs/mock-team/MARAM.md")

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan:
        raise NotImplementedError("Maram: S05 response; see docs/mock-team/MARAM.md")
