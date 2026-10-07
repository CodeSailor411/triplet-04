from typing import Any

from civis_brain.contracts import Plan, PlanningContext


class FixtureTwin:
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Maram: implement Twin fixture; see docs/mock-team/MARAM.md")


class FixtureGuardian:
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Maram: implement Guardian fixture after Elyes freezes mapping")


class FixturePlanProvider:
    async def generate(self, context: PlanningContext) -> Plan:
        raise NotImplementedError("Maram: return recorded Plan fixtures, never call a live AI API")
