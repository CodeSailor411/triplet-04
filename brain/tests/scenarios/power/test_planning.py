from civis_mock_peers.peers import FixturePlanProvider

from civis_brain.contracts import Incident, PlanningContext, ReadingsBatch
from civis_brain.scenarios.power.service import PowerScenario


async def test_power_response_never_calls_ai_or_proposes_grid_action():
    batch = ReadingsBatch(
        run_id="run-1", tick=1, time="2026-10-08T08:00:01Z", tick_seconds=1.0, count=0, readings=[]
    )
    incident = Incident(
        incident_id="power-1",
        kind="power_fault",
        run_id="run-1",
        domains=["power"],
        node_ids=["POW-01"],
        source_reading_ids=["r1"],
    )
    provider = FixturePlanProvider({"fixture_only": True, "ai_plan": {"proposals": []}})
    plan = await PowerScenario().draft_plan(
        PlanningContext(batch=batch, incidents=[incident], nodes=[], actions=[]), provider
    )
    assert len(plan.alerts) == 1 and not plan.proposals and not provider.calls
    assert "confirmed fault" in plan.alerts[0]
