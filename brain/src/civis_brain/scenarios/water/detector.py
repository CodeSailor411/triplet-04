"""S02 high-water candidate detector. Policy values are fixture-only."""

from civis_brain.contracts import (
    DetectionResult,
    Incident,
    Node,
    Observation,
    Reading,
    ReadingsBatch,
)


def classify(reading: Reading, domains_by_node: dict, policy: dict) -> Observation:
    """Mark a water_level reading usable or not; null is kept, never made zero."""
    domains = domains_by_node.get(reading.node_id, [])
    reason = None
    if "water" not in domains:
        reason = "node is not a water node"
    elif reading.value is None:
        reason = "null value"
    elif reading.unit != policy["unit"]:
        reason = f"unexpected unit {reading.unit}"
    return Observation(
        reading=reading, domains=domains, usable=reason is None, reason=reason
    )


def detect_high_water(
    batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict
) -> DetectionResult:
    # A new run starts with an empty history.
    if state.get("run_id") != batch.run_id:
        state.clear()
        state["run_id"] = batch.run_id
        state["streaks"] = {}
    streaks = state["streaks"]
    needed = max(1, int(policy["persistence_ticks"]))
    threshold = float(policy["threshold_min"])
    domains_by_node = {n.node_id: list(n.domains) for n in nodes}

    observations: list[Observation] = []
    highest: dict[str, Reading] = {}  # per node, the highest usable reading
    for reading in batch.readings:
        if reading.sensor != policy["sensor"]:
            continue
        obs = classify(reading, domains_by_node, policy)
        observations.append(obs)
        if obs.usable:
            current = highest.get(reading.node_id)
            if current is None or reading.value > current.value:
                highest[reading.node_id] = reading

    incidents: list[Incident] = []
    for node_id, reading in highest.items():
        streak = streaks.get(node_id, {"last_tick": None, "reading_ids": []})
        last_tick = streak["last_tick"]
        if last_tick is not None and reading.tick <= last_tick:
            continue  # duplicate or stale tick: no extra persistence
        if reading.value < threshold:
            streaks[node_id] = {"last_tick": reading.tick, "reading_ids": []}
            continue
        consecutive = (
            last_tick is not None
            and reading.tick == last_tick + 1
            and bool(streak["reading_ids"])
        )
        ids = streak["reading_ids"] if consecutive else []
        ids = (ids + [reading.reading_id])[-needed:]
        streaks[node_id] = {"last_tick": reading.tick, "reading_ids": ids}
        if len(ids) >= needed:
            supported = [
                c
                for c in policy.get("safe_valve_choices", [])
                if c.get("incident_node_id") == node_id
            ]
            incidents.append(
                Incident(
                    incident_id=f"flood:{batch.run_id}:{node_id}",
                    kind="flood",
                    run_id=batch.run_id,
                    domains=domains_by_node[node_id],
                    node_ids=[node_id],
                    source_reading_ids=list(ids),
                    facts={
                        "mock_only": True,
                        "unit": policy["unit"],
                        "threshold_min": threshold,
                        "persistence_ticks": needed,
                        "latest_value": reading.value,
                        "supported_valve_actions": supported,
                    },
                )
            )
    return DetectionResult(observations=observations, incidents=incidents)