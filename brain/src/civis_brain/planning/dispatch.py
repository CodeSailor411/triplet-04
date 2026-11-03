"""Common one-unit dispatch planning. Approval and execution belong to the runtime."""

from dataclasses import dataclass

from civis_brain.context_graph import ContextGraph
from civis_brain.contracts import Plan, PlanningContext
from civis_brain.errors import BrainError
from civis_brain.planning.service import DISPATCH_UNITS, validate_command


@dataclass(frozen=True)
class DispatchProfile:
    kind: str
    unit_type: str
    report_sensor: str
    report_channel: str | None
    report_unit: str
    availability_fact: str
    confirmed_report: bool = False


MEDICAL = DispatchProfile(
    "medical", "ambulance", "emergency_calls", "medical", "calls/min",
    "ambulance_available_by_carrier",
)


async def draft_dispatch(context: PlanningContext, provider, *, profile: DispatchProfile) -> Plan:
    """One primary unit per incident; no inferred injuries or optional secondary action.

    Fire/accident callers must supply their reviewed report convention. Arbitrary
    new unit types are never accepted just because a fixture advertises them.
    """
    if profile.unit_type not in DISPATCH_UNITS.get(profile.kind, set()):
        raise BrainError("UNITS_UNSUPPORTED", "Dispatch unit type is not supported")
    actions = [a for a in context.actions if a.action == "dispatch" and a.domain == "emergency"]
    if len(actions) != 1:
        return Plan(proposals=[])
    action = actions[0]
    if action.risk != "R2" or (action.action_cap is not None and action.action_cap < 1):
        return Plan(proposals=[])
    evidence = {r.reading_id: r for r in context.evidence_readings}
    if len(evidence) != len(context.evidence_readings):
        return Plan(proposals=[])
    nodes = {n.node_id: n for n in context.nodes}
    destination_domain = "traffic" if profile.kind == "road_accident" else "emergency"
    candidates = []
    for incident in context.incidents:
        if (incident.kind != profile.kind or incident.run_id != context.batch.run_id
                or destination_domain not in incident.domains or len(incident.node_ids) != 1
                or incident.facts.get("destination") != incident.node_ids[0]
                or not set(incident.source_reading_ids).issubset(evidence)
                or len(set(incident.source_reading_ids)) != len(incident.source_reading_ids)):
            continue
        destination = nodes.get(incident.node_ids[0])
        if destination is None or destination_domain not in destination.domains:
            continue
        reports, available = [], {}
        valid = True
        facts = incident.facts.get(profile.availability_fact, {})
        if not isinstance(facts, dict):
            continue
        for source in incident.source_reading_ids:
            reading = evidence[source]
            if reading.run_id != incident.run_id or reading.value is None:
                valid = False
                break
            if reading.sensor == profile.report_sensor:
                if (reading.node_id != destination.node_id
                        or reading.channel != profile.report_channel
                        or reading.unit != profile.report_unit or reading.value < 0
                        or (profile.confirmed_report and reading.value != 1)):
                    valid = False
                    break
                reports.append(reading)
            elif reading.sensor == "units_free":
                if (reading.channel != profile.unit_type or reading.unit != "units"
                        or reading.tick != context.batch.tick or reading.value < 0
                        or not reading.value.is_integer()
                        or reading.model_dump(mode="json") not in facts.get(reading.node_id, [])):
                    valid = False
                    break
                available.setdefault(reading.node_id, []).append(reading)
            else:
                valid = False
                break
        if not valid or not reports:
            continue
        for carrier_id in action.target_nodes:
            carrier = nodes.get(carrier_id)
            rows = available.get(carrier_id, [])
            if (carrier is None or "emergency" not in carrier.domains
                    or "dispatch" not in carrier.actuators or len(rows) != 1 or rows[0].value < 1):
                continue
            params = {"unit_type": profile.unit_type, "destination": destination.node_id, "units": 1}
            try:
                validate_command(action, [carrier_id], params, context.nodes)
            except BrainError:
                continue
            candidates.append((incident, carrier_id, params))
    if not candidates:
        return Plan(proposals=[])
    parameters = []
    for spec in action.params:
        spec = dict(spec)
        if spec["name"] == "units":
            spec.update(min_value=1, max_value=1)
        elif spec["name"] == "unit_type":
            spec["choices"] = [profile.unit_type]
        parameters.append(spec)
    geographic = dict(context.graph_context)
    graph = ContextGraph(context.nodes)
    rankings = {
        incident.incident_id: graph.rank_eligible(incident.node_ids[0], [
            carrier for candidate, carrier, _ in candidates
            if candidate.incident_id == incident.incident_id])
        for incident, _, _ in candidates
    }
    if any(row["distance_m"] is not None for rows in rankings.values() for row in rows):
        geographic.update(graph_version=graph.version, eligible_dispatch=rankings,
                          ranking_basis="geographic reference only; road reachability unknown")
    restricted = context.model_copy(update={"graph_context": geographic, "actions": [action.model_copy(update={
        "params": parameters, "target_nodes": sorted({c[1] for c in candidates}),
    })]})
    generated = await provider.generate(restricted)
    accepted, assigned = [], set()
    for proposal in generated.proposals:
        for incident, carrier_id, params in candidates:
            if (incident.incident_id not in assigned and proposal.action == "dispatch"
                    and proposal.risk == "R2" and proposal.preview_required == action.preview_required
                    and proposal.targets == [carrier_id] and proposal.params == params
                    and len(set(proposal.source_reading_ids)) == len(proposal.source_reading_ids)
                    and set(proposal.source_reading_ids) == set(incident.source_reading_ids)):
                reason = ("Dispatch one available ambulance to the reported medical-event location "
                          "using supplied evidence." if profile.kind == "medical" else
                          f"Dispatch one available {profile.unit_type} unit to the reported "
                          f"{profile.kind} location using supplied evidence.")
                accepted.append(proposal.model_copy(update={"reason": reason}))
                assigned.add(incident.incident_id)
                break
    alerts = list(generated.alerts)
    if len(accepted) != len(generated.proposals):
        alerts.append("Dispatch proposal rejected: require one available matching unit, "
                      "the reported destination and exact incident evidence.")
    return Plan(proposals=accepted, alerts=alerts)
