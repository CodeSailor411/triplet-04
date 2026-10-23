"""One synthetic live AI check; never calls Guardian/Twin or executes a command."""

import asyncio

from civis_brain.errors import BrainError
from civis_brain.planning.gemini import GeminiPlanProvider
from civis_brain.planning.service import validate_plan
from civis_brain.planning.smoke import synthetic_context
from civis_brain.settings import Settings


async def main():
    settings = Settings()
    provider = GeminiPlanProvider(
        settings.gemini_api_key, settings.gemini_model, settings.ai_timeout_seconds
    )
    context = synthetic_context()
    try:
        plan = validate_plan(context, await provider.generate(context))
        print(
            f"PASS: one synthetic Gemini response; {len(plan.proposals)} proposals, "
            f"{len(plan.alerts)} alerts; zero peer/effect calls"
        )
    except BrainError as error:
        raise SystemExit(f"{error.code}: {error.message}") from None
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
