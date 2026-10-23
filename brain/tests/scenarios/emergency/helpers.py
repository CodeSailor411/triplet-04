import json
from pathlib import Path
from typing import Any

from civis_brain.contracts import ActionInfo, Node, Plan, PlanningContext, ReadingsBatch

CASE_DIRECTORY = Path(__file__).resolve().parents[3] / "mocks" / "cases" / "emergency"


def load_case(filename: str) -> dict[str, Any]:
    with (CASE_DIRECTORY / filename).open(encoding="utf-8") as case_file:
        return json.load(case_file)


def load_nodes(case: dict[str, Any]) -> list[Node]:
    return [Node.model_validate(node) for node in case["nodes"]]


def load_actions(case: dict[str, Any]) -> list[ActionInfo]:
    return [ActionInfo.model_validate(action) for action in case["actions"]]


def load_batches(case: dict[str, Any]) -> list[ReadingsBatch]:
    return [ReadingsBatch.model_validate(batch) for batch in case["batches"]]


class RecordedPlanProvider:
    def __init__(self, case: dict[str, Any]) -> None:
        self.plan = Plan.model_validate(case["ai_plan"])
        self.calls: list[PlanningContext] = []

    async def generate(self, context: PlanningContext) -> Plan:
        self.calls.append(context)
        return self.plan