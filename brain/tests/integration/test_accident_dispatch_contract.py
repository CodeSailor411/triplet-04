"""S06 shared-core contract, with an explicit wrapper around Yassine's detector.

His submitted planner stays unchanged. This models the incident/facts his next
step must supply, using synthetic evidence and peers, never live authorization.
"""

import pytest
from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.contracts import ReadingsBatch
from civis_brain.integration.runtime import BrainRuntime
from civis_brain.planning.dispatch import DispatchProfile, draft_dispatch
from civis_brain.scenarios.traffic.accident import RoadAccidentScenario

from .helpers import make_case


@pytest.mark.parametrize("change,expected", [(None, "committed"), ("denied", "blocked"),
                                           ("unavailable", "blocked"), ("not_advertised", "blocked")])
async def test_police_can_respond_to_traffic_location_through_shared_core(change, expected):
    case = make_case("S05")
    case["scenario_id"] = "S06"
    case["nodes"][0]["domains"] = ["traffic"]
    report, availability = case["batches"][0]["readings"]
    report.update(sensor="road_accident_report", channel=None, unit="report", value=1.0)
    availability["channel"] = "police"
    if change == "unavailable":
        availability["value"] = 0.0
    case["actions"][0]["params"][0]["choices"] = ["ambulance"] if change == "not_advertised" else ["police"]
    case["ai_plan"]["proposals"][0]["params"]["unit_type"] = "police"
    case["guardian"]["approve"] = change != "denied"
    twin, guardian, provider = FixtureTwin(case), FixtureGuardian(case), FixturePlanProvider(case)

    class AccidentContractWrapper(RoadAccidentScenario):
        def detect(self, batch, nodes, policy, state):
            result = super().detect(batch, nodes, policy, state)
            rows = [r for r in batch.readings if r.sensor == "units_free" and r.channel == "police"]
            for incident in result.incidents:
                incident.facts.update(destination=incident.node_ids[0],
                    police_available_by_carrier={r.node_id: [r.model_dump(mode="json")] for r in rows})
                incident.source_reading_ids.extend(r.reading_id for r in rows)
            return result

        async def draft_plan(self, context, provider):
            return await draft_dispatch(context, provider, profile=DispatchProfile(
                kind="road_accident", unit_type="police", report_sensor="road_accident_report",
                report_channel=None, report_unit="report", availability_fact="police_available_by_carrier",
                confirmed_report=True))

    runtime = BrainRuntime(twin=twin, guardian=guardian, provider=provider,
        scenarios=(AccidentContractWrapper(),), policies={"S06": {"fixture_only": True}},
        features={"enabled_scenario_ids": ["S06"], "guardian_score_tool": "fixture_score",
                  "guardian_token_tool": "fixture_approve", "ai_max_calls_per_run": 2})
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].status == expected
    assert len(twin.effects) == int(expected == "committed")
    if expected == "committed":
        effect = twin.effects[0]
        assert effect["targets"] == ["N2"]
        assert effect["params"] == {"unit_type": "police", "destination": "N1", "units": 1}
        assert case["nodes"][0]["domains"] == ["traffic"]
    if change in {"unavailable", "not_advertised"}:
        assert not provider.calls
