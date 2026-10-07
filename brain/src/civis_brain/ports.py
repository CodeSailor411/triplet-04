"""Interfaces implemented by live adapters (Elyes) and fixture adapters (Maram)."""

from typing import Any, Protocol

from civis_brain.contracts import Plan, PlanningContext


class ToolPeer(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class PlanProvider(Protocol):
    async def generate(self, context: PlanningContext) -> Plan: ...
