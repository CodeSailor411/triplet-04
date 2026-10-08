"""One synthetic live AI check; never calls Guardian/Twin or executes a command."""

import asyncio

from civis_brain.contracts import (
    ActionInfo,
    Incident,
    Node,
    PlanningContext,
    Reading,
    ReadingsBatch,
)
from civis_brain.errors import BrainError
from civis_brain.planning.gemini import GeminiPlanProvider
from civis_brain.planning.service import validate_plan
from civis_brain.settings import Settings


async def main():
    settings = Settings()
    provider = GeminiPlanProvider(
        settings.gemini_api_key, settings.gemini_model, settings.ai_timeout_seconds
    )
    reading = Reading(
        run_id="synthetic-ai-smoke",
        reading_id="synthetic-r1",
        tick=1,
        timestamp="2026-10-08T08:00:01Z",
        node_id="SYNTHETIC-01",
        device_id="synthetic-device",
        sensor="congestion_index",
        channel=None,
        value=95.0,
        unit="percent",
    )
    batch = ReadingsBatch(
        run_id=reading.run_id,
        tick=1,
        time=reading.timestamp,
        tick_seconds=1.0,
        count=1,
        readings=[reading],
    )
    context = PlanningContext(
        batch=batch,
        evidence_readings=[reading],
        incidents=[
            Incident(
                incident_id="synthetic-candidate",
                kind="congestion",
                run_id=reading.run_id,
                domains=["traffic"],
                node_ids=[reading.node_id],
                source_reading_ids=[reading.reading_id],
                facts={"fixture_only": True},
            )
        ],
        nodes=[
            Node(
                node_id=reading.node_id,
                domains=["traffic"],
                role="fixture",
                actuators=["set_signal_plan"],
            )
        ],
        actions=[
            ActionInfo(
                action="set_signal_plan",
                domain="traffic",
                risk="R1",
                preview_required=False,
                target_nodes=[reading.node_id],
                action_cap=1,
                params=[{"name": "plan", "type": "choice", "choices": ["mock_priority"]}],
            )
        ],
    )
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
