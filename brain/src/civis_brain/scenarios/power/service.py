from civis_brain.contracts import DetectionResult, Node, Plan, PlanningContext, ReadingsBatch
from civis_brain.ports import PlanProvider


class PowerScenario:
    scenario_id = "S03"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        raise NotImplementedError("Elyes: S03 detection; see docs/mock-team/ELYES.md")

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan:
        raise NotImplementedError("Elyes: S03 response; see docs/mock-team/ELYES.md")
