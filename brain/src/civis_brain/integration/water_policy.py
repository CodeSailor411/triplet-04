"""Validate explicit Water command policies against actual Twin discovery."""

from civis_brain.contracts import ActionInfo, Node
from civis_brain.errors import BrainError
from civis_brain.planning.service import validate_command


def validate_water_choices(policy, node_list, action_list, *, mock_profile):
    """Check a supplied command policy against current read-only Twin discovery.

    This establishes carrier/parameter compatibility, never hydraulic safety.
    The shipped allowlist is usable only in the explicit mock profile.
    """
    if (not isinstance(node_list, dict) or not isinstance(action_list, dict)
            or not isinstance(node_list.get("nodes"), list)
            or not isinstance(action_list.get("actions"), list)
            or any(not isinstance(raw, dict) for raw in node_list["nodes"])
            or any(not isinstance(raw, dict) for raw in action_list["actions"])):
        raise BrainError("PEER_SCHEMA_INVALID", "Twin Water discovery must contain object lists")
    if policy.get("policy_scope") == "virtual-command-test-only" and not mock_profile:
        raise BrainError("MOCK_POLICY_REQUIRED", "Virtual valve choices need the mock profile")
    expected_seed = policy.get("expected_twin_seed")
    if expected_seed is not None and (
        type(expected_seed) is not int or node_list.get("seed") != expected_seed
    ):
        raise BrainError("TOPOLOGY_MISMATCH", "Valve policy belongs to another Twin seed")
    nodes = [Node.model_validate(raw) for raw in node_list["nodes"]]
    by_id = {node.node_id: node for node in nodes}
    if len(by_id) != len(nodes):
        raise BrainError("PEER_SCHEMA_INVALID", "Duplicate node IDs in Twin discovery")
    actions = [ActionInfo.model_validate(raw) for raw in action_list["actions"]
               if raw.get("action") == "set_valve_position"]
    if len(actions) != 1:
        raise BrainError("PEER_SCHEMA_INVALID", "Discover exactly one valve action")
    action = actions[0]
    if action.domain != "water" or action.risk != "R3" or not action.preview_required:
        raise BrainError("PREVIEW_MISMATCH", "Valve manifest must retain Water R3 and preview")
    position = next((spec for spec in action.params if spec.get("name") == "position"), {})
    if position.get("unit") not in {"%", "percent", "pct"}:
        raise BrainError("UNIT_MISMATCH", "Valve position must be advertised as percent")
    choices = policy.get("safe_valve_choices")
    if not isinstance(choices, list) or not choices:
        raise BrainError("TOPOLOGY_UNAVAILABLE", "Supply S02 safe_valve_choices in SCENARIO_POLICY_FILE")
    raw_nodes = {raw["node_id"]: raw for raw in node_list["nodes"]}
    for choice in choices:
        if not isinstance(choice, dict):
            raise BrainError("TOPOLOGY_UNAVAILABLE", "Valve choices must be objects")
        incident = by_id.get(choice.get("incident_node_id"))
        if incident is None or "water" not in incident.domains:
            raise BrainError("INVALID_TARGETS", "Valve incident node is not a discovered Water node")
        sensors = raw_nodes[incident.node_id].get("sensors", [])
        if not isinstance(sensors, list) or any(not isinstance(sensor, dict) for sensor in sensors):
            raise BrainError("PEER_SCHEMA_INVALID", "Water sensor discovery must be an object list")
        if not any(sensor.get("name") == policy.get("sensor")
                   and sensor.get("unit") == policy.get("unit") for sensor in sensors):
            raise BrainError("UNIT_MISMATCH", "Incident sensor and unit differ from Twin discovery")
        targets, params = choice.get("targets"), choice.get("params")
        if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
            raise BrainError("INVALID_TARGETS", "Valve targets must be node IDs")
        if not isinstance(params, dict):
            raise BrainError("INVALID_PARAMS", "Valve params must be an object")
        validate_command(action, targets, params, nodes)
        if any(set(by_id[target].domains) != {"water"}
               or action.action not in by_id[target].actuators for target in targets):
            raise BrainError("INVALID_TARGETS", "Mock valve carrier must advertise Water-only actuation")
        if (type(action.action_cap) is not int or action.action_cap < len(targets)):
            raise BrainError("CAP_EXCEEDED", "Valve choice exceeds its discovered Water action cap")
    return {
        "choices": len(choices),
        "seed": node_list.get("seed"),
        "scope": "Command compatibility only; no hydraulic or supply-safety assertion",
    }
