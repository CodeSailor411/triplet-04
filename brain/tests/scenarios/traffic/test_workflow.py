"""S01 through the shared runtime, using real detector and recorded partner responses."""
import copy

import pytest

from civis_brain.contracts import Node, ReadingsBatch
from civis_brain.scenarios.traffic.service import TrafficScenario
from tests.integration.test_member_integration import case_for, evaluate, harness


@pytest.mark.parametrize("variant", ["base", "refusal"])
async def test_traffic_workflow_exact_command_and_no_duplicate_effect(variant, tmp_path):
    case = case_for("traffic", variant)
    runtime, twin, guardian, provider = harness(case, tmp_path)
    results = await evaluate(case, runtime, twin)
    assert results[0].decisions == []
    decision = results[-1].decisions[0]
    expected = case["expected"]
    assert decision.status == expected["final_statuses"][0]
    for field in ("action", "targets", "params", "source_reading_ids", "peer_code"):
        assert getattr(decision, field) == expected[field]
    assert len(twin.effects) == expected["effects"]
    assert len(provider.calls) == 1
    assert sum(row["name"] == "fixture_score" for row in guardian.calls) == 1
    assert sum(row["name"] == "fixture_approve" for row in guardian.calls) == 1
    calls_before = len(twin.calls), len(guardian.calls), len(provider.calls)
    repeat = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][-1]))
    assert repeat == results[-1]
    assert (len(twin.calls), len(guardian.calls), len(provider.calls)) == calls_before
    assert runtime.explain_decision(decision.decision_id)["found"]


@pytest.mark.parametrize("change", [
    {"unit": "km/h"}, {"channel": "unexpected"}, {"value": None},
    {"value": -1}, {"value": 101}, {"value": 79},
])
async def test_invalid_or_low_traffic_readings_never_request_approval(change, tmp_path):
    case = case_for("traffic")
    for batch in case["batches"]:
        batch["readings"][0].update(change)
    runtime, twin, guardian, provider = harness(case, tmp_path)
    await evaluate(case, runtime, twin)
    assert not provider.calls and not guardian.calls and not twin.effects


async def test_current_twin_metrics_do_not_invent_congestion_index(tmp_path):
    case = case_for("traffic")
    for batch in case["batches"]:
        batch["readings"][0].update(sensor="avg_speed", value=5, unit="km/h")
    runtime, twin, guardian, provider = harness(case, tmp_path)
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].status == "alert"
    assert "no agreed conversion" in result.decisions[0].reason
    assert not provider.calls and not guardian.calls and not twin.effects


@pytest.mark.parametrize("overrides", [
    {"threshold_min": None}, {"threshold_min": float("nan")},
    {"threshold_min": float("inf")}, {"threshold_min": True},
    {"persistence_ticks": 0}, {"persistence_ticks": 101}, {"persistence_ticks": True},
])
async def test_invalid_policy_cannot_authorize_a_signal(overrides, tmp_path):
    case = case_for("traffic")
    case["policy"].update(overrides)
    runtime, twin, guardian, provider = harness(case, tmp_path)
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].peer_code == "SCENARIO_INVALID"
    assert not provider.calls and not twin.effects


async def test_ambiguous_sensors_do_not_arbitrarily_select_the_first(tmp_path):
    case = case_for("traffic")
    for batch in case["batches"]:
        other = copy.deepcopy(batch["readings"][0])
        other.update(device_id="other-sensor", reading_id=other["reading_id"]+"-other", value=10)
        batch["readings"].append(other)
        batch["count"] += 1
    runtime, twin, _, provider = harness(case, tmp_path)
    await evaluate(case, runtime, twin)
    assert not provider.calls and not twin.effects


def test_persistence_keeps_full_window_and_shared_domains_without_rewinding_state():
    case = case_for("traffic")
    policy = {**case["policy"], "persistence_ticks": 3}
    case["nodes"][0]["domains"].append("power")
    nodes = [Node.model_validate(n) for n in case["nodes"]]
    scenario, state = TrafficScenario(), {}
    batch = ReadingsBatch.model_validate(case["batches"][0])
    for tick in range(1, 20):
        reading = batch.readings[0].model_copy(update={"tick": tick, "reading_id": f"r{tick}"})
        result = scenario.detect(batch.model_copy(update={"tick": tick, "readings": [reading]}),
                                 nodes, policy, state)
        if tick >= 3:
            assert result.incidents[0].source_reading_ids == [f"r{i}" for i in range(tick-2,tick+1)]
            assert result.incidents[0].domains == ["traffic", "power"]
    before = copy.deepcopy(state)
    assert not scenario.detect(batch, nodes, policy, state).incidents
    assert before == state
    assert len(state["s01_traffic"]["nodes"]["TRAFFIC-01"]["evidence"]) == 3


@pytest.mark.parametrize("change", ["missing_parameter", "partial_evidence", "unrelated_carrier"])
async def test_planner_rejects_invalid_intents(change, tmp_path):
    case = case_for("traffic")
    proposal = case["ai_plan"]["proposals"][0]
    if change == "missing_parameter":
        proposal["params"] = {}
    elif change == "partial_evidence":
        proposal["source_reading_ids"] = ["traffic-2"]
    else:
        node = copy.deepcopy(case["nodes"][0])
        node["node_id"] = "UNRELATED"
        case["nodes"].append(node)
        case["actions"][0]["target_nodes"].append(node["node_id"])
        proposal["targets"] = [node["node_id"]]
    runtime, twin, guardian, _ = harness(case, tmp_path)
    await evaluate(case, runtime, twin)
    assert not twin.effects
    assert not any(row["name"] == "fixture_approve" for row in guardian.calls)
