"""Read-only discovery checks for the explicitly scoped Twin mock Water policy."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from civis_brain import preflight
from civis_brain.errors import BrainError
from civis_brain.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def discovery():
    policy = json.loads((ROOT / "config/scenarios/water.json").read_text())
    overrides = json.loads((ROOT / "config/integration/twin-mock-3.json").read_text())
    policy.update(overrides["S02"])
    nodes = {"seed": 42, "nodes": [
        {"node_id": "WAT-01", "domains": ["water"], "role": "standard",
         "actuators": ["set_valve_position"], "neighbours": [],
         "sensors": [{"name": "water_level", "unit": "cm"}]},
        {"node_id": "WAT-02", "domains": ["water"], "role": "standard",
         "actuators": [], "neighbours": [], "sensors": []},
    ]}
    actions = {"actions": [{
        "action": "set_valve_position", "domain": "water", "risk": "R3",
        "preview_required": True, "target_nodes": ["WAT-01"], "action_cap": 2,
        "params": [{"name": "position", "type": "number", "min_value": 0,
                    "max_value": 100, "unit": "%"}],
    }]}
    return policy, nodes, actions


def test_mock_water_profile_is_explicit_and_does_not_replace_detection_thresholds():
    policy, nodes, actions = discovery()
    override = json.loads((ROOT / "config/integration/twin-mock-3.json").read_text())
    assert "threshold_min" not in override["S02"]
    assert policy["threshold_min"] == 100.0
    assert policy["persistence_ticks"] == 2
    assert policy["fixture_only"] is True
    assert override["S07"] == {"enabled": False, "supply_nodes": [], "safe_valve_choices": []}
    result = preflight.validate_water_choices(policy, nodes, actions, mock_profile=True)
    assert result["choices"] == 1
    assert result["seed"] == 42
    assert "no hydraulic" in result["scope"]


def test_virtual_valve_policy_cannot_be_mistaken_for_physical_safety_configuration():
    with pytest.raises(BrainError, match="mock profile") as error:
        preflight.validate_water_choices(*discovery(), mock_profile=False)
    assert error.value.code == "MOCK_POLICY_REQUIRED"


@pytest.mark.parametrize(("mutation", "code"), [
    (lambda p, n, a: n.update(seed=7), "TOPOLOGY_MISMATCH"),
    (lambda p, n, a: p.update(safe_valve_choices=[]), "TOPOLOGY_UNAVAILABLE"),
    (lambda p, n, a: p["safe_valve_choices"][0].update(incident_node_id="missing"), "INVALID_TARGETS"),
    (lambda p, n, a: p["safe_valve_choices"][0].update(targets=["WAT-02"]), "INVALID_TARGETS"),
    (lambda p, n, a: n["nodes"][0].update(domains=["water", "power"]), "INVALID_TARGETS"),
    (lambda p, n, a: n["nodes"][0].update(actuators=[]), "INVALID_TARGETS"),
    (lambda p, n, a: n["nodes"][0].update(sensors=[]), "UNIT_MISMATCH"),
    (lambda p, n, a: n["nodes"][0].update(sensors=["water_level"]), "PEER_SCHEMA_INVALID"),
    (lambda p, n, a: n["nodes"][0]["sensors"][0].update(unit="m"), "UNIT_MISMATCH"),
    (lambda p, n, a: a["actions"][0].update(risk="R2"), "PREVIEW_MISMATCH"),
    (lambda p, n, a: a["actions"][0].update(preview_required=False), "PREVIEW_MISMATCH"),
    (lambda p, n, a: a["actions"][0]["params"][0].update(unit="fraction"), "UNIT_MISMATCH"),
    (lambda p, n, a: a["actions"][0]["params"][0].update(max_value=1), "INVALID_PARAMS"),
    (lambda p, n, a: p["safe_valve_choices"][0].update(params={"position": True}), "INVALID_PARAMS"),
    (lambda p, n, a: a["actions"][0].update(action_cap=0), "CAP_EXCEEDED"),
    (lambda p, n, a: n["nodes"].append(copy.deepcopy(n["nodes"][0])), "PEER_SCHEMA_INVALID"),
    (lambda p, n, a: a["actions"].append(None), "PEER_SCHEMA_INVALID"),
])
def test_changed_or_missing_discovery_never_passes_from_a_nonempty_list(mutation, code):
    policy, nodes, actions = discovery()
    mutation(policy, nodes, actions)
    with pytest.raises(BrainError) as error:
        preflight.validate_water_choices(policy, nodes, actions, mock_profile=True)
    assert error.value.code == code


@pytest.mark.asyncio
async def test_preflight_reads_live_discovery_and_never_calls_action_tools(monkeypatch):
    policy, nodes, actions = discovery()
    calls = []
    names = {"get_capabilities", "get_clock", "list_nodes", "list_actions", "get_readings",
             "get_containment_state", "actuate", "preview_action", "describe_capabilities",
             "get_trust_verdict", "authorize_action"}

    class ReadOnlyPeer:
        async def list_tool_names(self):
            return list(names)

        async def call_tool(self, name, arguments):
            calls.append(name)
            return {
                "list_nodes": nodes,
                "list_actions": actions,
                "get_clock": {"run_id": "mock-run", "tick": 1},
                "get_readings": {
                    "run_id": "mock-run", "tick": 1, "time": "2026-10-26T08:00:01Z",
                    "tick_seconds": 1.0, "count": 1, "readings": [{
                        "run_id": "mock-run", "reading_id": "traffic-1", "tick": 1,
                        "timestamp": "2026-10-26T08:00:01Z", "node_id": "TRF-01",
                        "device_id": "TRF-01.congestion_index", "sensor": "congestion_index",
                        "channel": None, "value": 10.0, "unit": "percent",
                    }],
                },
                "get_capabilities": {"thresholds": {"reading": 0.7}},
            }[name]

    closed = []

    async def close():
        closed.append(True)

    peer = ReadOnlyPeer()
    runtime = SimpleNamespace(policies={"S02": policy}, guardian=peer, close=close,
                              _validate_clock=lambda batch, clock: None)
    monkeypatch.setattr(preflight, "configured_runtime", lambda settings: runtime)
    monkeypatch.setattr(preflight, "MCPPeer", lambda *args: peer)
    result = await preflight.check(Settings(
        _env_file=None, peer_mode="live", llm_mode="gemini", gemini_api_key="test-only-key",
        twin_feed_enabled=True, mock_integration_profile=True,
        guardian_transport="mcp_v3", guardian_contract_confirmed=True,
    ))
    assert result["ready"] is True
    assert any(row["check"] == "water_topology" and row["passed"] for row in result["checks"])
    assert "list_nodes" in calls and "list_actions" in calls
    assert not set(calls) & {"preview_action", "actuate", "authorize_action", "get_trust_verdict"}
    assert closed == [True]
