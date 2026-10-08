import hashlib

from civis_brain.contracts import Incident, Node, Observation, ReadingsBatch


def observations(batch: ReadingsBatch, nodes: list[Node], units: dict) -> list[Observation]:
    node_map = {node.node_id: node for node in nodes}
    result = []
    for reading in batch.readings:
        if reading.sensor not in units:
            continue
        usable = (
            reading.value is not None
            and reading.unit == units[reading.sensor]
            and reading.channel is None
        )
        result.append(
            Observation(
                reading=reading,
                domains=node_map[reading.node_id].domains,
                usable=usable,
                reason=None if usable else "Missing value or unexpected unit",
            )
        )
    return result


def reset_state(state: dict, run_id: str) -> None:
    if state.get("run_id") != run_id:
        state.clear()
        state.update(run_id=run_id, streaks={})


def persistence(observation: Observation, policy: dict, state: dict) -> list[str]:
    reading = observation.reading
    key = (reading.node_id, reading.sensor, reading.channel)
    old = state["streaks"].get(key, {})
    count = policy["persistence_ticks"]
    if type(count) is not int or count < 1:
        raise ValueError("Persistence must be an integer of at least one tick")
    if old.get("tick", -1) >= reading.tick:
        saved = old.get("evidence", [])
        return saved if old.get("tick") == reading.tick and len(saved) >= count else []
    elevated = observation.usable and reading.value >= policy["threshold_min"]
    evidence = []
    if elevated:
        if old.get("tick") == reading.tick - 1 and old.get("qualifies"):
            evidence = old.get("evidence", []).copy()
        evidence.append(reading.reading_id)
    evidence = evidence[-count:]
    state["streaks"][key] = {"tick": reading.tick, "qualifies": elevated, "evidence": evidence}
    return evidence if len(evidence) >= count else []


def candidate(kind: str, observation: Observation, evidence: list[str], facts: dict) -> Incident:
    reading = observation.reading
    identity = f"{reading.run_id}:{kind}:{reading.node_id}"
    return Incident(
        incident_id=hashlib.sha256(identity.encode()).hexdigest()[:24],
        kind=kind,
        run_id=reading.run_id,
        domains=observation.domains,
        node_ids=[reading.node_id],
        source_reading_ids=evidence,
        facts=facts,
    )
