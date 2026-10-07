from civis_brain.contracts import Plan, PlanningContext
from civis_brain.ports import PlanProvider


async def draft_plan(context: PlanningContext, provider: PlanProvider) -> Plan:
    """Meriem: request a typed proposal. This function never calls Twin or Guardian."""
    raise NotImplementedError("Meriem: implement draft_plan; see docs/mock-team/MERIEM.md")
