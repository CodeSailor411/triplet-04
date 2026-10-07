from civis_brain.contracts import Plan, PlanningContext


def validate_plan(context: PlanningContext, plan: Plan) -> Plan:
    """Elyes: validate scenario proposals against evidence and discovered actions."""
    raise NotImplementedError("Elyes: shared plan validation; see docs/mock-team/ELYES.md")
