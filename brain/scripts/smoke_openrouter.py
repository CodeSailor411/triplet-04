"""One synthetic OpenRouter call; no Twin/Guardian call or execution."""

import asyncio

from civis_brain.errors import BrainError
from civis_brain.planning.openrouter import OpenRouterPlanProvider
from civis_brain.planning.service import validate_plan
from civis_brain.planning.smoke import synthetic_context
from civis_brain.settings import Settings


async def main():
    settings = Settings()
    provider = OpenRouterPlanProvider(
        settings.openrouter_api_key, settings.openrouter_model, settings.ai_timeout_seconds
    )
    try:
        plan = validate_plan(synthetic_context(), await provider.generate(synthetic_context()))
        print(
            f"PASS: OpenRouter Gemma JSON Plan validated; {len(plan.proposals)} proposals, "
            f"{len(plan.alerts)} alerts; zero peer/effect calls"
        )
    except BrainError as error:
        raise SystemExit(f"{error.code}: {error.message}") from None
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
