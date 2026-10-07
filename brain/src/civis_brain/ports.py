"""Shared ports for one runtime and five independently owned scenario modules."""

from typing import Any, Protocol

from civis_brain.contracts import DetectionResult, Node, Plan, PlanningContext, ReadingsBatch


class ToolPeer(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class PlanProvider(Protocol):
    async def generate(self, context: PlanningContext) -> Plan: ...


class Scenario(Protocol):
    scenario_id: str

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult: ...

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan: ...
