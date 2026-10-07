from typing import Any

from civis_brain.contracts import Plan, PlanningContext


class FixtureTwin:
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Elyes: implement reusable Twin fixture for all five scenarios")


class FixtureGuardian:
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Elyes: implement reusable Guardian fixture after mapping is frozen")


class FixturePlanProvider:
    async def generate(self, context: PlanningContext) -> Plan:
        raise NotImplementedError("Elyes: load recorded Plan data; never call a live AI API")
