"""Shared traffic/AQ carriers use Twin's sensor-only null-cap convention."""

import copy

import pytest

from civis_brain.contracts import ReadingsBatch
from civis_brain.integration.action_caps import discover_action_caps

from .helpers import harness, make_case


def discovery():
    case = make_case()
    case["nodes"][0]["domains"].append("air_quality")
    case["nodes"].append({"node_id": "AIR-01", "domains": ["air_quality"],
                          "role": "standard", "actuators": [], "neighbours": []})
    return case, {"count": 2, "nodes": case["nodes"]}, {
        "actions": case["actions"],
        "isolation_caps": [{"domain": "traffic", "isolation_cap": 2},
                           {"domain": "air_quality", "isolation_cap": 1}],
    }


def test_complete_discovery_resolves_sensor_only_domain_without_using_isolation_limit():
    _, nodes, actions = discovery()
    assert discover_action_caps(nodes, actions, {}) == {"traffic": 2, "air_quality": None}


@pytest.mark.parametrize("change", ["missing_count", "partial_nodes", "missing_actuators",
                                   "missing_roster", "missing_standalone", "unknown_actuator",
                                   "wrong_carrier", "missing_actuator_manifest"])
def test_incomplete_discovery_never_becomes_an_unlimited_domain(change):
    _, nodes, actions = discovery()
    if change == "missing_count":
        nodes.pop("count")
    elif change == "partial_nodes":
        nodes["count"] = 3
    elif change == "missing_actuators":
        nodes["nodes"][1].pop("actuators")
    elif change == "missing_roster":
        actions.pop("isolation_caps")
    elif change == "missing_standalone":
        nodes["nodes"] = nodes["nodes"][:1]
        nodes["count"] = 1
    elif change == "unknown_actuator":
        nodes["nodes"][0]["actuators"].append("unlisted_switch")
    elif change == "wrong_carrier":
        actions["actions"][0]["target_nodes"] = []
    elif change == "missing_actuator_manifest":
        nodes["nodes"][1]["actuators"] = ["air_switch"]
    assert "air_quality" not in discover_action_caps(nodes, actions, {})


def test_explicit_action_caps_are_preserved_including_zero():
    _, nodes, actions = discovery()
    assert discover_action_caps(nodes, actions, {"air_quality": 0})["air_quality"] == 0


@pytest.mark.parametrize("cap,expected", [(None, "committed"), (0, "blocked")])
async def test_shared_carrier_full_runtime_preserves_finite_limits(cap, expected):
    case, nodes, actions = discovery()
    case["caps"]["air_quality"] = cap
    runtime, twin, guardian, _ = harness(case)
    original = twin.call_tool

    async def call(name, args):
        if name == "get_capabilities" and cap is None:
            response = await original(name, args)
            response.pop("action_caps")  # Native Twin supplies only list_actions caps.
            return response
        if name == "list_nodes":
            return copy.deepcopy(nodes)
        if name == "list_actions":
            return copy.deepcopy(actions)
        return await original(name, args)

    twin.call_tool = call
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].status == expected
    assert len(twin.effects) == int(expected == "committed")
    if expected == "blocked":
        assert result.decisions[0].peer_code == "CAP_EXCEEDED"
        assert not any(row["name"] == "fixture_approve" for row in guardian.calls)
