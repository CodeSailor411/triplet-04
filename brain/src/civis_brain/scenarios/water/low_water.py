"""S07 low-water supply detector and scenario. Policy values are fixture-only.

Separate from S02 on purpose: strictly-below logic, its own state, its own
reviewed valve choices. Nothing is shared with detect_high_water.
"""

from math import isfinite

from civis_brain.contracts import (
    DetectionResult,
    Incident,
    Node,
    Observation,
    Plan,
    PlanningContext,
    Reading,
    ReadingsBatch,
)
from civis_brain.ports import PlanProvider
from civis_brain.scenarios.water.planner import plan_response


def _number(value) -> bool:
    return type(value) in (int, float) and isfinite(value)


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def policy_error(policy: dict) -> str | None:
    """Return why a low-water policy is invalid, or None."""
    if policy.get("scenario_id") != "S07":
        return "scenario_id is not S07"
    if not _text(policy.get("sensor")):
        return "sensor missing"
    if not _text(policy.get("unit")):
        return "unit missing"
    if not _text(policy.get("datum")):
        return "local datum missing"
    nodes = policy.get("supply_nodes")
    if not isinstance(nodes, list) or not nodes or not all(_text(n) for n in nodes):
        return "no reviewed supply nodes"
    low, recovery = policy.get("threshold_max"), policy.get("recovery_level")
    if not _number(low) or not _number(recovery):
        return "threshold_max or recovery_level is not a finite number"
    if recovery <= low:
        return "recovery_level must be above threshold_max"
    needed = policy.get("persistence_ticks")
    if type(needed) is not int or not 1 <= needed <= 100:
        return "persistence_ticks must be an int from 1 to 100"
    return None


def pair_error(high_policy: dict, low_policy: dict) -> str | None:
    """Cross-check S02 and S07 policies. Call at startup, before running."""
    high = high_policy.get("threshold_min")
    if not _number(high):
        return "high-water threshold_min missing or invalid"
    if high_policy.get("unit") != low_policy.get("unit"):
        return "high and low policies use different units"
    if not _number(low_policy.get("threshold_max")) or not _number(low_policy.get("recovery_level")):
        return "low-water thresholds missing or invalid"
    if low_policy["threshold_max"] >= high:
        return "low threshold is not below the high threshold"
    if low_policy["recovery_level"] >= high:
        return "low-water recovery level overlaps the high-water band"
    return None


def reviewed_choices(policy: dict, node_id: str) -> list[dict]:
    """Only choices explicitly reviewed as supply-preserving for this node.

    A choice without the review fields (for example one copied from S02) is
    never exposed, so its valve direction cannot be reused blindly.
    """
    return [
        c
        for c in policy.get("safe_valve_choices", [])
        if c.get("incident_node_id") == node_id
        and c.get("supply_preserving") is True
        and _text(c.get("reviewed_topology_ref"))
    ]


def classify(reading: Reading, domains_by_node: dict, policy: dict) -> Observation:
    domains = domains_by_node.get(reading.node_id, [])
    reason = None
    if "water" not in domains:
        reason = "node is not a water node"
    elif reading.node_id not in policy["supply_nodes"]:
        reason = "node is not a reviewed supply node"
    elif reading.channel is not None:
        reason = "unexpected water_level channel"
    elif reading.value is None:
        reason = "null value"
    elif reading.unit != policy["unit"]:
        reason = f"unexpected unit {reading.unit}"
    return Observation(reading=reading, domains=domains, usable=reason is None, reason=reason)


def detect_low_water(
    batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
) -> DetectionResult:
    if state.get("run_id") != batch.run_id:  # a new run starts with empty history
        state.clear()
        state["run_id"] = batch.run_id
        state["nodes"] = {}
    problem = policy_error(policy)
    if problem:
        return DetectionResult(
            observations=[], incidents=[], warnings=[f"S07 detection disabled: {problem}"]
        )
    node_state = state["nodes"]
    threshold, recovery = policy["threshold_max"], policy["recovery_level"]
    needed = policy["persistence_ticks"]
    domains_by_node = {n.node_id: list(n.domains) for n in nodes}

    observations: list[Observation] = []
    lowest: dict[str, Reading] = {}  # per node, the lowest usable reading
    for reading in batch.readings:
        if reading.sensor != policy["sensor"]:
            continue
        obs = classify(reading, domains_by_node, policy)
        observations.append(obs)
        if obs.usable:
            current = lowest.get(reading.node_id)
            if current is None or reading.value < current.value:
                lowest[reading.node_id] = reading

    incidents: list[Incident] = []
    for node_id, reading in lowest.items():
        prev = node_state.get(node_id, {"last_tick": None, "reading_ids": [], "armed": True})
        last = prev["last_tick"]
        if last is not None and reading.tick <= last:
            continue  # duplicate or stale tick: no extra persistence
        if reading.value >= recovery:  # recovered: clear streak, re-arm
            node_state[node_id] = {"last_tick": reading.tick, "reading_ids": [], "armed": True}
            continue
        if reading.value >= threshold:  # not low (equal counts as not low), not yet recovered
            node_state[node_id] = {
                "last_tick": reading.tick, "reading_ids": [], "armed": prev["armed"],
            }
            continue
        consecutive = last is not None and reading.tick == last + 1 and bool(prev["reading_ids"])
        was_firing = consecutive and len(prev["reading_ids"]) >= needed
        ids = ((prev["reading_ids"] if consecutive else []) + [reading.reading_id])[-needed:]
        fire = len(ids) >= needed and (prev["armed"] or was_firing)
        node_state[node_id] = {
            "last_tick": reading.tick, "reading_ids": ids, "armed": prev["armed"] and not fire,
        }
        if fire:
            incidents.append(
                Incident(
                    incident_id=f"low_water:{batch.run_id}:{node_id}",
                    kind="low_water",
                    run_id=batch.run_id,
                    domains=domains_by_node[node_id],
                    node_ids=[node_id],
                    source_reading_ids=list(ids),
                    facts={
                        "mock_only": True,
                        "unit": policy["unit"],
                        "datum": policy["datum"],
                        "threshold_max": threshold,
                        "recovery_level": recovery,
                        "persistence_ticks": needed,
                        "latest_value": reading.value,
                        "supported_valve_actions": reviewed_choices(policy, node_id),
                    },
                )
            )
    return DetectionResult(observations=observations, incidents=incidents)


class LowWaterScenario:
    scenario_id = "S07"

    def detect(
        self, batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
    ) -> DetectionResult:
        return detect_low_water(batch, nodes, policy, state)

    async def draft_plan(self, context: PlanningContext, provider: PlanProvider) -> Plan:
        return await plan_response(
            context, provider, kind="low_water", label="Low-water supply candidate"
        )