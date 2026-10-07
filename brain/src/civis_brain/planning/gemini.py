from civis_brain.contracts import Plan, PlanningContext


class GeminiPlanProvider:
    def __init__(self, api_key: str, model: str, timeout_seconds: float = 15):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate(self, context: PlanningContext) -> Plan:
        """Elyes: one shared free-API adapter, constrained JSON and no tool execution."""
        raise NotImplementedError("Elyes: shared Gemini adapter is assigned, not implemented")
