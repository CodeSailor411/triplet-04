from civis_brain.contracts import Plan, PlanningContext


class GeminiPlanProvider:
    def __init__(self, api_key: str, model: str, timeout_seconds: float = 15):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate(self, context: PlanningContext) -> Plan:
        """Meriem: implement with google-genai, schema-constrained JSON and no tools."""
        raise NotImplementedError("Meriem: Gemini adapter is assigned, not implemented")
