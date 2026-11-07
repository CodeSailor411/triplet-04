"""Resolve Twin's per-domain action limits without inventing numeric caps."""

from civis_brain.errors import BrainError


def discover_action_caps(nodes_response: dict, actions_response: dict, advertised: dict) -> dict:
    if not isinstance(advertised, dict):
        raise BrainError("PEER_SCHEMA_INVALID", "action_caps must be a domain mapping")
    caps = dict(advertised)
    actions = actions_response["actions"]
    for action in actions:
        caps.setdefault(action["domain"], action["action_cap"])

    # Twin's complete list_actions omits sensor-only domains: compute_caps gives
    # them action_cap=None. isolation_caps supplies the configured domain roster,
    # NOT an action limit. Require complete, consistent node/actuator discovery
    # and a sensor-only standalone node before using that null-cap convention.
    nodes = nodes_response["nodes"]
    if (type(nodes_response.get("count")) is not int
            or nodes_response["count"] != len(nodes)
            or len({node["node_id"] for node in nodes}) != len(nodes)
            or any(not isinstance(node.get("actuators"), list) for node in nodes)):
        return caps
    roster = actions_response.get("isolation_caps")
    if not isinstance(roster, list):
        return caps
    domains = {row.get("domain") for row in roster if isinstance(row, dict)
               and isinstance(row.get("domain"), str)}
    manifest = {row["action"]: row for row in actions}
    if len(manifest) != len(actions):
        return caps
    for domain in domains - caps.keys():
        members = [node for node in nodes if domain in node["domains"]]
        standalone = [node for node in members if node["domains"] == [domain]]
        if not standalone or any(node["actuators"] for node in standalone):
            continue
        if all(
            name in manifest
            and manifest[name]["domain"] in node["domains"]
            and node["node_id"] in manifest[name]["target_nodes"]
            for node in members for name in node["actuators"]
        ):
            caps[domain] = None
    return caps
