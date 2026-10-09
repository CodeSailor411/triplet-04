from copy import deepcopy

import pytest

from civis_brain.scenarios.emergency.service import EmergencyScenario
from tests.scenarios.emergency.helpers import load_batches, load_case, load_nodes


@pytest.fixture
def base_case():
    return load_case("base_case.json")


def test_detects_medical_event_and_preserves_call_and_carrier_evidence(base_case):
    detector = EmergencyScenario()
    batch = load_batches(base_case)[0]
    nodes = load_nodes(base_case)

    result = detector.detect(batch, nodes, base_case["policy"], {})

    assert detector.scenario_id == "S05"
    assert len(result.incidents) == 1
    incident = result.incidents[0]
    assert incident.kind == "medical"
    assert incident.node_ids == ["EMG-INCIDENT-01"]
    assert incident.domains == ["emergency"]
    assert incident.incident_id == "S05:fixture-s05-base:EMG-INCIDENT-01:medical"
    assert incident.source_reading_ids == ["s05-base-calls-01", "s05-base-units-01"]
    assert incident.facts == {
        "destination": "EMG-INCIDENT-01",
        "ambulance_available_by_carrier": {
            "EMG-CARRIER-01": [batch.readings[1].model_dump(mode="json")]
        },
    }
    assert all(observation.usable for observation in result.observations)


def test_medical_call_below_configured_threshold_has_no_candidate(base_case):
    policy = base_case["policy"]
    batch = load_batches(base_case)[0]
    readings = [
        reading.model_copy(update={"value": policy["threshold_min"] - 0.01})
        if reading.sensor == policy["sensor"]
        else reading
        for reading in batch.readings
    ]

    result = EmergencyScenario().detect(
        batch.model_copy(update={"readings": readings}),
        load_nodes(base_case),
        policy,
        {},
    )

    assert result.incidents == []
    event_observation = next(
        observation
        for observation in result.observations
        if observation.reading.sensor == policy["sensor"]
    )
    assert event_observation.usable
    assert event_observation.reading.value < policy["threshold_min"]


def test_medical_call_at_configured_threshold_creates_candidate(base_case):
    policy = base_case["policy"]
    batch = load_batches(base_case)[0]
    readings = [
        reading.model_copy(update={"value": policy["threshold_min"]})
        if reading.sensor == policy["sensor"]
        else reading
        for reading in batch.readings
    ]

    result = EmergencyScenario().detect(
        batch.model_copy(update={"readings": readings}),
        load_nodes(base_case),
        policy,
        {},
    )

    assert len(result.incidents) == 1
    incident = result.incidents[0]
    assert incident.kind == "medical"
    assert incident.source_reading_ids == ["s05-base-calls-01", "s05-base-units-01"]


@pytest.mark.parametrize(
    ("updates", "expected_reason"),
    [
        ({"value": None}, "reading value is null"),
        ({"unit": "calls"}, "unexpected emergency_calls unit"),
        ({"channel": "transcript"}, "unexpected emergency_calls channel"),
    ],
)
def test_ignores_null_or_mismatched_medical_reading(base_case, updates, expected_reason):
    batch = load_batches(base_case)[0]
    readings = [
        reading.model_copy(update=updates) if reading.sensor == "emergency_calls" else reading
        for reading in batch.readings
    ]
    modified_batch = batch.model_copy(update={"readings": readings})

    result = EmergencyScenario().detect(modified_batch, load_nodes(base_case), base_case["policy"], {})

    assert result.incidents == []
    medical_observation = next(
        observation for observation in result.observations
        if observation.reading.sensor == "emergency_calls"
    )
    assert not medical_observation.usable
    assert medical_observation.reason == expected_reason


def test_duplicate_tick_does_not_advance_persistence_or_change_incident_identity(base_case):
    policy = {**base_case["policy"], "persistence_ticks": 2}
    batch = load_batches(base_case)[0]
    nodes = load_nodes(base_case)
    state = {}
    detector = EmergencyScenario()

    first = detector.detect(batch, nodes, policy, state)
    state_after_first = deepcopy(state)
    duplicate = detector.detect(batch, nodes, policy, state)

    assert first.incidents == duplicate.incidents == []
    assert state == state_after_first

    next_batch = batch.model_copy(
        update={
            "tick": 2,
            "time": "2026-10-09T09:01:00Z",
            "readings": [
                reading.model_copy(
                    update={
                        "tick": 2,
                        "timestamp": "2026-10-09T09:01:00Z",
                        "reading_id": reading.reading_id.replace("-01", "-02"),
                    }
                )
                for reading in batch.readings
            ],
        }
    )
    detected = detector.detect(next_batch, nodes, policy, state)
    repeated = detector.detect(next_batch, nodes, policy, state)

    assert len(detected.incidents) == 1
    assert detected.incidents == repeated.incidents
    assert detected.incidents[0].source_reading_ids == [
        "s05-base-calls-01",
        "s05-base-calls-02",
        "s05-base-units-02",
    ]


def test_new_run_resets_persistence_history(base_case):
    policy = {**base_case["policy"], "persistence_ticks": 2}
    batch = load_batches(base_case)[0]
    nodes = load_nodes(base_case)
    state = {}
    detector = EmergencyScenario()

    assert detector.detect(batch, nodes, policy, state).incidents == []
    new_run_batch = batch.model_copy(
        update={
            "run_id": "fixture-s05-new-run",
            "tick": 2,
            "time": "2026-10-09T09:01:00Z",
            "readings": [
                reading.model_copy(
                    update={
                        "run_id": "fixture-s05-new-run",
                        "tick": 2,
                        "timestamp": "2026-10-09T09:01:00Z",
                    }
                )
                for reading in batch.readings
            ],
        }
    )

    result = detector.detect(new_run_batch, nodes, policy, state)

    assert result.incidents == []
    assert state["_s05_run_id"] == "fixture-s05-new-run"
    assert state["_s05_events_by_node"]["EMG-INCIDENT-01"]["streak"] == 1