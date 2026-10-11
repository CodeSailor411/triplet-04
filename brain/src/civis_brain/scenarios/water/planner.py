"""S02 constrained response. Proposes only; never approves, previews or executes."""

from civis_brain.contracts import (
    ActionInfo,
    ActionProposal,
    Incident,
    Plan,
    PlanningContext,
)
from civis_brain.ports import PlanProvider

ACTION = "set_valve_position"
RISK = "R3"


def flood_incidents(context: PlanningContext) -> list[Incident]:
    return [i for i in context.incidents if i.kind == "flood"]


def find_manifest(context: PlanningContext) -> ActionInfo | None:
    for info in context.actions:
        if info.action == ACTION and info.domain == "water":
            return info
    return None


def _within_bounds(spec: dict, value) -> bool:
    low, high = spec.get("min_value"), spec.get("max_value")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return spec.get("type") != "number"
    if low is not None and value < low:
        return False
    return not (high is not None and value > high)


def manifest_allows(info: ActionInfo, choice: dict) -> bool:
    """A configured valve choice is usable only if the manifest supports it."""
    specs = {p.get("name"): p for p in info.params}
    targets = choice.get("targets") or []
    params = choice.get("params") or {}
    if not targets or not params:
        return False
    if not set(targets) <= set(info.target_nodes):
        return False
    return all(
        name in specs and _within_bounds(specs[name], value)
        for name, value in params.items()
    )


def rejection_reason(
    proposal: ActionProposal, incident: Incident, info: ActionInfo, choices: list[dict]
) -> str | None:
    """Return why a proposal is not allowed, or None if it matches exactly."""
    if proposal.action != ACTION:
        return f"unknown action {proposal.action}"
    if not proposal.source_reading_ids:
        return "proposal has no evidence ids"
    if proposal.risk != RISK:
        return f"risk {proposal.risk} is not {RISK}"
    if proposal.preview_required != info.preview_required:
        return "preview_required does not match the manifest"
    if not set(proposal.source_reading_ids) <= set(incident.source_reading_ids):
        return "evidence ids not produced by the detector"
    for choice in choices:
        if sorted(proposal.targets) == sorted(choice["targets"]) and (
            proposal.params == choice["params"]
        ):
            return None
    return "targets or params are not a supported valve choice"


async def plan_response(context: PlanningContext, provider: PlanProvider) -> Plan:
    incidents = flood_incidents(context)
    if not incidents:
        return Plan(proposals=[], alerts=[])

    info = find_manifest(context)
    alerts: list[str] = []
    actionable: list[tuple[Incident, list[dict]]] = []
    for incident in incidents:
        node = ", ".join(incident.node_ids)
        raw = incident.facts.get("supported_valve_actions") or []
        choices = [c for c in raw if info is not None and manifest_allows(info, c)]
        if choices:
            actionable.append((incident, choices))
        else:
            alerts.append(
                f"High-water candidate at {node}: no supported valve action; "
                "alert only, no valve change proposed."
            )

    if not actionable or info is None:
        return Plan(proposals=[], alerts=alerts)

    plan = await provider.generate(context)  # exactly one call per attempt
    kept: list[ActionProposal] = []
    for proposal in plan.proposals:
        reasons = [
            rejection_reason(proposal, incident, info, choices)
            for incident, choices in actionable
        ]
        if any(reason is None for reason in reasons):
            kept.append(proposal)
        else:
            alerts.append(f"Dropped proposal: {reasons[0]}")
    return Plan(proposals=kept, alerts=alerts + list(plan.alerts))