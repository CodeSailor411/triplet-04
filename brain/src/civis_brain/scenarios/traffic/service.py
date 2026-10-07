from civis_brain.contracts import DetectionResult, Node, Plan, PlanningContext, ReadingsBatch
from civis_brain.ports import PlanProvider


class TrafficScenario:
    scenario_id = "S01"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        raise NotImplementedError("Yassine: S01 detection; see docs/mock-team/YASSINE.md")

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan:
        raise NotImplementedError("Yassine: S01 response; see docs/mock-team/YASSINE.md")
