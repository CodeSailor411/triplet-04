import copy
import json
from pathlib import Path

import pytest

from civis_brain.contracts import ActionInfo, Node, Plan, PlanningContext, ReadingsBatch
from civis_brain.errors import BrainError
from civis_brain.integration.runtime import BrainRuntime
from civis_brain.planning.dispatch import DispatchProfile, draft_dispatch
from civis_brain.planning.service import validate_plan
from civis_brain.scenarios.emergency.fire import FireScenario

from .test_member_integration import evaluate, harness
from .test_oct19 import advance

ROOT = Path(__file__).resolve().parents[2]


def low_case():
    return json.loads((ROOT / "mocks/cases/water/low_base_case.json").read_text())


@pytest.mark.parametrize("latest_value,expected", [(29.0, "committed"), (30.0, "blocked"),
                                                    (40.0, "blocked"), (45.0, "blocked")])
async def test_s07_revalidates_low_direction_during_planning(latest_value, expected, tmp_path):
    case = low_case()
    runtime, twin, _, provider = harness(case, tmp_path)
    runtime.features["max_evidence_age_seconds"] = 60
    original = provider.generate

    async def plan(context):
        result = await original(context)
        raw = advance(case["batches"][-1])
        raw["readings"][0]["value"] = latest_value
        twin.advance(raw)
        runtime.observe_feed(ReadingsBatch.model_validate(raw))
        return result

    provider.generate = plan
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].status == expected
    assert len(twin.effects) == int(expected == "committed")
    if expected == "blocked":
        assert result.decisions[0].peer_code == "EVIDENCE_CHANGED"


async def test_s07_recovery_requires_hysteresis_then_rearms(tmp_path):
    case = low_case()
    runtime, twin, _, provider = harness(case, tmp_path)
    runtime.features["one_response_per_episode"] = True
    await evaluate(case, runtime, twin)
    assert len(twin.effects) == 1
    original_episode = dict(runtime.episodes)
    raw = case["batches"][-1]
    previous = raw["readings"][0]["reading_id"]
    for value in (40.0, 45.0, 20.0, 15.0):
        raw = advance(raw)
        raw["readings"][0]["value"] = value
        if value == 40:
            expected_episode = original_episode
        else:
            expected_episode = None
        provider.case["ai_plan"]["proposals"][0]["source_reading_ids"] = (
            [previous, raw["readings"][0]["reading_id"]] if value == 15 else
            [raw["readings"][0]["reading_id"]])
        twin.advance(raw)
        await runtime.evaluate_tick(ReadingsBatch.model_validate(raw))
        if expected_episode is not None:
            assert runtime.episodes == expected_episode
        previous = raw["readings"][0]["reading_id"]
    assert len(twin.effects) == 2
    requests = [c["arguments"] for c in twin.calls if c["name"] == "actuate"]
    assert len({r["idempotency_key"] for r in requests}) == 2


@pytest.mark.parametrize("value", [0.0, -1.0, 0.5, 2.0])
def test_fire_report_must_be_positive_confirmation(value):
    case = json.loads((ROOT / "mocks/cases/emergency/s08_supported_fire_report.json").read_text())
    case["batches"][0]["readings"][0]["value"] = value
    result = FireScenario().detect(ReadingsBatch.model_validate(case["batches"][0]),
                                  [Node.model_validate(n) for n in case["nodes"]], case["policy"], {})
    assert not result.incidents


async def test_common_dispatch_supports_advertised_fire_without_member_planner():
    case = json.loads((ROOT / "mocks/cases/emergency/s08_supported_fire_report.json").read_text())
    case = copy.deepcopy(case)
    case["policy"].update(unit_type="fire", availability_channel="fire")
    case["batches"][0]["readings"][1]["channel"] = "fire"
    case["actions"][0]["params"][0]["choices"] = ["fire", "ambulance"]
    case["ai_plan"]["proposals"][0]["params"]["unit_type"] = "fire"
    batch = ReadingsBatch.model_validate(case["batches"][0])
    nodes = [Node.model_validate(n) for n in case["nodes"]]
    detected = FireScenario().detect(batch, nodes, case["policy"], {})
    context = PlanningContext(batch=batch, nodes=nodes, incidents=detected.incidents,
                              evidence_readings=batch.readings,
                              actions=[ActionInfo.model_validate(a) for a in case["actions"]])

    class Provider:
        async def generate(self, ctx):
            choices = next(p["choices"] for p in ctx.actions[0].params if p["name"] == "unit_type")
            assert choices == ["fire"]
            return Plan.model_validate(case["ai_plan"])

    policy = case["policy"]
    profile = DispatchProfile("fire", "fire", policy["report_sensor"], policy["report_channel"],
                              policy["report_unit"], "firefighter_available_by_carrier", True)
    plan = await draft_dispatch(context, Provider(), profile=profile)
    assert len(validate_plan(context, plan).proposals) == 1
    plan.proposals[0].params["unit_type"] = "ambulance"
    with pytest.raises(BrainError):
        validate_plan(context, plan)


@pytest.mark.parametrize("available,expected_effects", [(1.0, 1), (2.0, 2)])
async def test_competing_incidents_cannot_allocate_the_same_unit_twice(available, expected_effects, tmp_path):
    from .test_member_integration import case_for
    case = case_for("emergency")
    second_node = copy.deepcopy(case["nodes"][0])
    second_node["node_id"] = "second-location"
    case["nodes"].append(second_node)
    raw = case["batches"][0]
    second = {**raw["readings"][0], "node_id": "second-location", "reading_id": "second-call",
              "device_id": "second-device"}
    raw["readings"].append(second)
    raw["readings"][1]["value"] = available
    raw["count"] = len(raw["readings"])
    runtime, twin, guardian, provider = harness(case, tmp_path)

    async def plan(context):
        template = case["ai_plan"]["proposals"][0]
        return Plan.model_validate({"proposals": [
            {**template, "params": {**template["params"], "destination": incident.node_ids[0]},
             "source_reading_ids": incident.source_reading_ids}
            for incident in context.incidents]})

    provider.generate = plan
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(raw))
    assert len(twin.effects) == expected_effects, result
    assert sum(d.status == "committed" for d in result.decisions) == expected_effects
    approvals = [c for c in guardian.calls if c["name"] == "fixture_approve"]
    assert len(approvals) == expected_effects
    if available == 1:
        assert any(d.peer_code == "RESOURCE_RESERVED" for d in result.decisions)


@pytest.mark.parametrize("approved,expected", [(True, "committed"), (False, "blocked")])
async def test_shared_fire_contract_through_runtime_with_test_wrapper(approved, expected, tmp_path):
    """Exercise the shared core; the member's submitted Fire planner is still a stub."""
    from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

    case = json.loads((ROOT / "mocks/cases/emergency/s08_supported_fire_report.json").read_text())
    case["policy"].update(unit_type="fire", availability_channel="fire")
    case["batches"][0]["readings"][1]["channel"] = "fire"
    case["actions"][0]["params"][0]["choices"] = ["fire"]
    case["ai_plan"]["proposals"][0]["params"]["unit_type"] = "fire"
    case["guardian"]["approve"] = approved
    policy = case["policy"]

    class SharedFireWrapper(FireScenario):
        async def draft_plan(self, context, provider):
            return await draft_dispatch(context, provider, profile=DispatchProfile(
                "fire", "fire", policy["report_sensor"], policy["report_channel"], policy["report_unit"],
                "firefighter_available_by_carrier", True))

    twin, guardian, provider = FixtureTwin(case), FixtureGuardian(case), FixturePlanProvider(case)
    runtime = BrainRuntime(twin=twin, guardian=guardian, provider=provider,
        scenarios=(SharedFireWrapper(),), policies={"S08": policy}, artifact_dir=tmp_path,
        features={"enabled_scenario_ids": ["S08"], "guardian_score_tool": "fixture_score",
                  "guardian_token_tool": "fixture_approve", "ai_max_calls_per_run": 2})
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].status == expected
    assert len(twin.effects) == int(approved)
    assert provider.calls


async def test_s07_stale_evidence_during_planning_never_actuates(tmp_path):
    case = low_case()
    runtime, twin, guardian, provider = harness(case, tmp_path)
    original = provider.generate

    async def delayed(context):
        plan = await original(context)
        twin.advance(advance(case["batches"][-1], 2))
        return plan

    provider.generate = delayed
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].peer_code == "EVIDENCE_STALE"
    assert not twin.effects
    assert not any(c["name"] == "fixture_approve" for c in guardian.calls)
