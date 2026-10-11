from civis_brain.contracts import Node, Reading, ReadingsBatch
from civis_brain.scenarios.water.service import WaterScenario

POLICY = {
    "sensor": "water_level",
    "unit": "cm",
    "threshold_min": 100.0,
    "persistence_ticks": 2,
    "safe_valve_choices": [
        {"incident_node_id": "tank-01", "targets": ["valve-01"],
         "params": {"position_pct": 30}}
    ],
}
NODES = [Node(node_id="tank-01", domains=["water"], role="tank")]


def make_batch(tick, value, unit="cm", run="run-1"):
    reading = Reading(
        run_id=run,
        reading_id=f"w-{run}-{tick}",
        tick=tick,
        timestamp=f"2026-10-08T10:{tick:02d}:00Z",
        node_id="tank-01",
        device_id="lvl-01",
        sensor="water_level",
        channel=None,
        value=value,
        unit=unit,
    )
    return ReadingsBatch(
        run_id=run,
        tick=tick,
        time=reading.timestamp,
        tick_seconds=60.0,
        count=1,
        readings=[reading],
    )


def detect(batch, state):
    return WaterScenario().detect(batch, NODES, POLICY, state)


def test_normal_level_gives_no_incident():
    result = detect(make_batch(10, 60.0), {})
    assert result.incidents == []
    assert result.observations[0].usable


def test_single_high_tick_is_not_enough():
    assert detect(make_batch(10, 172.0), {}).incidents == []


def test_sustained_high_water_gives_flood_candidate():
    state = {}
    detect(make_batch(10, 172.0), state)
    incident = detect(make_batch(11, 178.0), state).incidents[0]
    assert incident.kind == "flood"
    assert incident.incident_id == "flood:run-1:tank-01"
    assert incident.node_ids == ["tank-01"]
    assert incident.source_reading_ids == ["w-run-1-10", "w-run-1-11"]
    assert incident.facts["supported_valve_actions"][0]["targets"] == ["valve-01"]


def test_duplicate_tick_does_not_extend_persistence():
    state = {}
    detect(make_batch(10, 172.0), state)
    assert detect(make_batch(10, 172.0), state).incidents == []


def test_new_run_resets_history():
    state = {}
    detect(make_batch(10, 172.0, run="run-1"), state)
    assert detect(make_batch(11, 178.0, run="run-2"), state).incidents == []


def test_null_value_is_ignored_and_breaks_the_streak():
    state = {}
    detect(make_batch(10, 172.0), state)
    nulled = detect(make_batch(11, None), state)
    assert nulled.observations[0].usable is False
    assert detect(make_batch(12, 180.0), state).incidents == []


def test_wrong_unit_is_unusable_and_never_converted():
    result = detect(make_batch(10, 2.0, unit="m"), {})
    assert result.observations[0].usable is False
    assert result.incidents == []


def test_no_valve_choice_means_empty_supported_actions():
    policy = {**POLICY, "safe_valve_choices": []}
    scenario, state = WaterScenario(), {}
    scenario.detect(make_batch(10, 172.0), NODES, policy, state)
    incident = scenario.detect(make_batch(11, 178.0), NODES, policy, state).incidents[0]
    assert incident.facts["supported_valve_actions"] == []