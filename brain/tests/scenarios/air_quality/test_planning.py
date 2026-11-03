from civis_mock_peers.peers import FixturePlanProvider

from civis_brain.contracts import Incident, PlanningContext, ReadingsBatch
from civis_brain.scenarios.air_quality.service import AirQualityScenario


async def test_air_response_cannot_turn_pollution_into_dispatch():
    batch = ReadingsBatch(
        run_id="run-1", tick=1, time="2026-10-08T08:00:01Z", tick_seconds=1.0, count=0, readings=[]
    )
    incident = Incident(
        incident_id="air-1",
        kind="air_pollution",
        run_id="run-1",
        domains=["air_quality", "emergency"],
        node_ids=["AQ-01"],
        source_reading_ids=["r1"],
    )
    provider = FixturePlanProvider({"fixture_only": True, "ai_plan": {"proposals": []}})
    plan = await AirQualityScenario().draft_plan(
        PlanningContext(batch=batch, incidents=[incident], nodes=[], actions=[]), provider
    )
    assert len(plan.alerts) == 1 and not plan.proposals and not provider.calls
    assert "no corroborated emergency dispatch" in plan.alerts[0]
