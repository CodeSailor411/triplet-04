
from civis_brain.contracts import Node, Reading, ReadingsBatch
from civis_brain.scenarios.traffic.service import TrafficScenario

POLICY = {
    "sensor": "congestion_index",
    "unit": "percent",
    "threshold_min": 80.0,
    "persistence_ticks": 2,
}


def reading(tick: int, value: float, run_id: str = "run-1", unit: str = "percent"):
    return Reading(
        run_id=run_id,
        reading_id=f"reading-{run_id}-{tick}",
        tick=tick,
        timestamp=f"2026-10-09T20:{tick:02d}:00Z",
        node_id="traffic-1",
        device_id="device-1",
        sensor="congestion_index",
        channel=None,
        value=value,
        unit=unit,
    )


def batch(item: Reading) -> ReadingsBatch:
    return ReadingsBatch(
        run_id=item.run_id,
        tick=item.tick,
        time=item.timestamp,
        tick_seconds=1.0,
        count=1,
        readings=[item],
    )


def nodes():
    return [Node(node_id="traffic-1", domains=["traffic"], role="sensor")]


def test_congestion_after_two_consecutive_ticks():
    scenario, state = TrafficScenario(), {}

    first = scenario.detect(batch(reading(1, 85.0)), nodes(), POLICY, state)
    second = scenario.detect(batch(reading(2, 90.0)), nodes(), POLICY, state)

    assert first.incidents == []
    assert len(second.incidents) == 1
    assert second.incidents[0].kind == "congestion"
    assert second.incidents[0].source_reading_ids == [
        "reading-run-1-1",
        "reading-run-1-2",
    ]


def test_low_value_resets_streak():
    scenario, state = TrafficScenario(), {}

    scenario.detect(batch(reading(1, 85.0)), nodes(), POLICY, state)
    scenario.detect(batch(reading(2, 40.0)), nodes(), POLICY, state)
    result = scenario.detect(batch(reading(3, 90.0)), nodes(), POLICY, state)

    assert result.incidents == []


def test_new_run_resets_streak():
    scenario, state = TrafficScenario(), {}

    scenario.detect(batch(reading(1, 85.0)), nodes(), POLICY, state)
    result = scenario.detect(
        batch(reading(2, 90.0, run_id="run-2")), nodes(), POLICY, state
    )

    assert result.incidents == []
    assert state["s01_traffic"]["run_id"] == "run-2"


def test_wrong_unit_is_unsupported():
    result = TrafficScenario().detect(
        batch(reading(1, 90.0, unit="km/h")), nodes(), POLICY, {}
    )

    assert result.observations[0].usable is False
    assert result.observations[0].reason == "unsupported_unit"
    assert result.incidents == []