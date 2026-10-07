from civis_brain.contracts import DetectionResult, Node, Plan, PlanningContext, ReadingsBatch
from civis_brain.ports import PlanProvider


class AirQualityScenario:
    scenario_id = "S04"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        raise NotImplementedError("Elyes: S04 detection; see docs/mock-team/ELYES.md")

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan:
        raise NotImplementedError("Elyes: S04 response; see docs/mock-team/ELYES.md")
