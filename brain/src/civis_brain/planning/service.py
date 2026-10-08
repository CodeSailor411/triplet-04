import math

from civis_brain.contracts import ActionInfo, ActionProposal, Node, Plan, PlanningContext, Reading
from civis_brain.errors import BrainError

PRIMARY_ACTIONS = {
    "set_signal_plan": ("congestion", "R1", False),
    "set_valve_position": ("flood", "R3", True),
    "dispatch": ("medical", "R2", False),
}


def validate_command(
    action: ActionInfo, targets: list[str], params: dict, nodes: list[Node]
) -> dict:
    node_ids = {node.node_id for node in nodes}
    if not targets or len(set(targets)) != len(targets):
        raise BrainError("INVALID_TARGETS", "Targets must be distinct existing carrier nodes")
    if not set(targets).issubset(set(action.target_nodes) & node_ids):
        raise BrainError("INVALID_TARGETS", "A target does not carry the advertised actuator")
    specs = {item["name"]: item for item in action.params}
    if set(params) != set(specs):
        raise BrainError("INVALID_PARAMS", "Parameter names must exactly match the manifest")
    normalized = {}
    for name, spec in specs.items():
        value = params[name]
        kind = spec["type"]
        if kind == "choice":
            valid = isinstance(value, str) and value in spec.get("choices", [])
        elif kind == "node":
            valid = isinstance(value, str) and value in node_ids
        elif kind in {"number", "integer"}:
            valid = (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(value)
                and (kind != "integer" or isinstance(value, int))
            )
            if valid and spec.get("min_value") is not None:
                valid = value >= spec["min_value"]
            if valid and spec.get("max_value") is not None:
                valid = value <= spec["max_value"]
        else:
            raise BrainError("PEER_SCHEMA_INVALID", "Unknown manifest parameter type")
        if not valid:
            raise BrainError("INVALID_PARAMS", "A parameter violates the discovered manifest")
        normalized[name] = float(value) if kind == "number" else value
    return normalized


def validate_plan(context: PlanningContext, plan: Plan) -> Plan:
    """Validate proposal semantics; trust/token/preview enforcement stays in the runtime."""
    evidence = {reading.reading_id: reading for reading in context.evidence_readings}
    allowed_evidence = {
        reading_id for incident in context.incidents for reading_id in incident.source_reading_ids
    }
    action_map = {action.action: action for action in context.actions}
    if len(action_map) != len(context.actions):
        raise BrainError("PEER_SCHEMA_INVALID", "Duplicate action name in discovery")
    if len(plan.proposals) > len(context.incidents):
        raise BrainError("AI_OUTPUT_INVALID", "Too many proposals for the supplied incidents")
    proposals = []
    for proposal in plan.proposals:
        if proposal.action not in PRIMARY_ACTIONS or proposal.action not in action_map:
            raise BrainError("UNKNOWN_ACTION", "Proposal is not an allowed primary response")
        kind, risk, required_preview = PRIMARY_ACTIONS[proposal.action]
        action = action_map[proposal.action]
        if action.risk != risk or proposal.risk != action.risk:
            raise BrainError("RISK_MISMATCH", "Risk must match the agreed actuator and manifest")
        if proposal.preview_required != action.preview_required or (
            required_preview and not action.preview_required
        ):
            raise BrainError("PREVIEW_MISMATCH", "Preview requirements cannot be relaxed")
        source_ids = set(proposal.source_reading_ids)
        if len(source_ids) != len(proposal.source_reading_ids) or not source_ids.issubset(
            allowed_evidence & set(evidence)
        ):
            raise BrainError("EVIDENCE_UNKNOWN", "Proposal contains missing or invented evidence")
        if any(evidence[source].value is None for source in source_ids):
            raise BrainError("EVIDENCE_INVALID", "Null readings cannot authorize an action")
        matching = [
            incident
            for incident in context.incidents
            if incident.kind == kind and set(incident.source_reading_ids).issubset(source_ids)
        ]
        if not matching:
            raise BrainError("EVIDENCE_INCOMPLETE", "Proposal must retain the incident evidence")
        params = validate_command(action, proposal.targets, proposal.params, context.nodes)
        if proposal.action == "set_signal_plan":
            node_map = {node.node_id: node for node in context.nodes}
            locations = {node_id for incident in matching for node_id in incident.node_ids}
            linked = locations | {
                neighbour for node_id in locations for neighbour in node_map[node_id].neighbours
            }
            if not set(proposal.targets).issubset(linked):
                raise BrainError("TARGET_UNRELATED", "Signal target has no supplied incident link")
        if proposal.action == "set_valve_position":
            choices = [
                choice
                for incident in matching
                for choice in incident.facts.get("supported_valve_actions", [])
            ]
            if not any(
                sorted(choice["targets"]) == sorted(proposal.targets) and choice["params"] == params
                for choice in choices
            ):
                raise BrainError(
                    "TOPOLOGY_UNAVAILABLE", "No supplied safe valve choice supports this intent"
                )
        if proposal.action == "dispatch":
            locations = {node_id for incident in matching for node_id in incident.node_ids}
            if params.get("destination") not in locations or params.get("unit_type") != "ambulance":
                raise BrainError(
                    "DESTINATION_INVALID", "Dispatch must match the reported medical location"
                )
            if params.get("units") != 1:
                raise BrainError("UNITS_UNSUPPORTED", "Primary medical mock requests one ambulance")
            for carrier in proposal.targets:
                available = [
                    reading
                    for reading in evidence.values()
                    if reading.node_id == carrier
                    and reading.sensor == "units_free"
                    and reading.channel == "ambulance"
                    and reading.unit == "units"
                    and reading.value is not None
                    and reading.reading_id in source_ids
                ]
                if not available or min(reading.value for reading in available) < 1:
                    raise BrainError(
                        "UNITS_UNAVAILABLE", "No usable ambulance availability evidence"
                    )
        proposals.append(
            proposal.model_copy(update={"targets": sorted(proposal.targets), "params": params})
        )
    identities = {(item.action, tuple(item.targets)) for item in proposals}
    if len(identities) != len(proposals):
        raise BrainError("DUPLICATE_PROPOSAL", "Duplicate action/carrier proposal in one plan")
    return Plan(proposals=proposals, alerts=plan.alerts)


def check_caps(proposal: ActionProposal, nodes: list[Node], caps: dict) -> None:
    node_map = {node.node_id: node for node in nodes}
    counts: dict[str, int] = {}
    for node_id in set(proposal.targets):
        for domain in set(node_map[node_id].domains):
            counts[domain] = counts.get(domain, 0) + 1
    for domain, requested in counts.items():
        if domain not in caps:
            raise BrainError("CAP_UNAVAILABLE", "A touched domain has no discovered action cap")
        limit = caps[domain]
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        ):
            raise BrainError(
                "PEER_SCHEMA_INVALID", "Action cap must be a non-negative integer or null"
            )
        if limit is not None and requested > limit:
            raise BrainError(
                "CAP_EXCEEDED",
                "The whole request exceeds a domain action cap",
                {
                    "domain": domain,
                    "cap": "action",
                    "limit": limit,
                    "already": 0,
                    "requested": requested,
                },
            )


def evidence_ids(readings: list[Reading]) -> set[str]:
    return {reading.reading_id for reading in readings}
