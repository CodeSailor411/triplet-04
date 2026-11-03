import pytest

from civis_brain.scenarios.emergency.fire import FireScenario
from tests.scenarios.emergency.helpers import load_batches, load_case, load_nodes


@pytest.fixture
def fire_case():
    return load_case("s08_supported_fire_report.json")


def _detect(case, batch=None, nodes=None, state=None):
    if batch is None:
        batch = load_batches(case)[0]
    if nodes is None:
        nodes = load_nodes(case)
    return FireScenario().detect(batch, nodes, case["policy"], state if state is not None else {})


def test_supported_report_preserves_report_identity_location_and_sources(fire_case):
    batch = load_batches(fire_case)[0]
    result = _detect(fire_case, batch=batch)

    assert len(result.incidents) == 1
    incident = result.incidents[0]
    assert incident.kind == "fire"
    assert incident.incident_id == "S08:fixture-s08-supported:s08-supported-fire-report-01:fire"
    assert incident.node_ids == ["FIRE-LOCATION-01"]
    assert incident.source_reading_ids == [
        "s08-supported-fire-report-01",
        "s08-supported-firefighter-availability-01",
    ]
    assert incident.facts["report_reading_id"] == "s08-supported-fire-report-01"
    assert incident.facts["destination"] == "FIRE-LOCATION-01"
    assert incident.facts["location"] == {
        "node_id": "FIRE-LOCATION-01",
        "lat": 51.5,
        "lon": -0.12,
    }
    assert incident.facts["firefighter_unit_type"] == "PROVISIONAL_FIREFIGHTER_UNIT_TYPE"
    assert all(observation.usable for observation in result.observations)


def test_pm25_spike_alone_is_not_a_fire_report():
    case = load_case("s08_air_pollution_only.json")
    result = _detect(case)

    assert result.incidents == []
    assert result.observations == []


@pytest.mark.parametrize(
    ("updates", "expected_reason"),
    [
        ({"value": None}, "reading value is null"),
        ({"channel": "different"}, "unexpected reported-fire channel"),
        ({"unit": "different"}, "unexpected reported-fire unit"),
    ],
)
def test_null_or_mismatched_report_is_not_a_candidate(fire_case, updates, expected_reason):
    batch = load_batches(fire_case)[0]
    report = batch.readings[0].model_copy(update=updates)
    modified = batch.model_copy(update={"readings": [report, *batch.readings[1:]]})

    result = _detect(fire_case, batch=modified)

    assert result.incidents == []
    observation = next(row for row in result.observations if row.reading.sensor == fire_case["policy"]["report_sensor"])
    assert not observation.usable
    assert observation.reason == expected_reason


def test_missing_location_coordinates_is_not_a_candidate(fire_case):
    batch = load_batches(fire_case)[0]
    report = batch.readings[0].model_copy(update={"lat": None, "lon": None})
    nodes = load_nodes(fire_case)
    location = next(node for node in nodes if node.node_id == report.node_id)
    location.lat = None
    location.lon = None

    result = _detect(
        fire_case,
        batch=batch.model_copy(update={"readings": [report, *batch.readings[1:]]}),
        nodes=nodes,
    )

    assert result.incidents == []
    report_observation = next(row for row in result.observations if row.reading.sensor == report.sensor)
    assert not report_observation.usable
    assert report_observation.reason == "reported-fire location has no coordinates"


def test_unknown_destination_node_is_not_a_candidate(fire_case):
    batch = load_batches(fire_case)[0]
    report = batch.readings[0].model_copy(update={"node_id": "UNKNOWN-FIRE-LOCATION"})

    result = _detect(
        fire_case,
        batch=batch.model_copy(update={"readings": [report, *batch.readings[1:]]}),
    )

    assert result.incidents == []
    report_observation = next(row for row in result.observations if row.reading.sensor == report.sensor)
    assert not report_observation.usable
    assert report_observation.reason == "destination node is not in discovery"


def test_untrusted_report_is_not_a_candidate(fire_case):
    batch = load_batches(fire_case)[0]
    state = {}
    detector = FireScenario()
    detector.detect(batch, load_nodes(fire_case), fire_case["policy"], state)
    state["_s08_untrusted_reading_ids"] = {batch.readings[0].reading_id}

    result = detector.detect(batch, load_nodes(fire_case), fire_case["policy"], state)

    assert result.incidents == []
    report_observation = next(row for row in result.observations if row.reading.sensor == batch.readings[0].sensor)
    assert not report_observation.usable
    assert report_observation.reason == "reading is marked untrusted"


def test_report_schema_values_are_read_from_policy(fire_case):
    batch = load_batches(fire_case)[0]
    report, availability = batch.readings
    policy = {
        **fire_case["policy"],
        "report_sensor": "configured_fire_sensor",
        "report_channel": "configured_fire_channel",
        "report_unit": "configured_fire_unit",
        "unit_type": "configured_firefighter_type",
        "availability_channel": "configured_firefighter_channel",
    }
    configured_batch = batch.model_copy(
        update={
            "readings": [
                report.model_copy(
                    update={
                        "sensor": policy["report_sensor"],
                        "channel": policy["report_channel"],
                        "unit": policy["report_unit"],
                    }
                ),
                availability.model_copy(
                    update={"channel": policy["availability_channel"]}
                ),
            ]
        }
    )

    result = FireScenario().detect(
        configured_batch, load_nodes(fire_case), policy, {}
    )

    assert len(result.incidents) == 1
    assert result.incidents[0].facts["firefighter_unit_type"] == "configured_firefighter_type"


def test_duplicate_and_repeated_report_keep_one_stable_episode(fire_case):
    case = load_case("s08_repeated_report.json")
    batches = load_batches(case)
    nodes = load_nodes(case)
    state = {}
    detector = FireScenario()

    first = detector.detect(batches[0], nodes, case["policy"], state)
    repeated = detector.detect(batches[1], nodes, case["policy"], state)
    duplicate_batch = batches[1].model_copy(
        update={
            "count": 3,
            "readings": [*batches[1].readings, batches[1].readings[0]],
        }
    )
    duplicate = detector.detect(duplicate_batch, nodes, case["policy"], state)

    assert len(first.incidents) == len(repeated.incidents) == len(duplicate.incidents) == 1
    incident_id = first.incidents[0].incident_id
    assert repeated.incidents[0].incident_id == incident_id
    assert duplicate.incidents[0].incident_id == incident_id
    assert repeated.incidents[0].source_reading_ids == [
        "s08-repeated-fire-report-identity",
        "s08-repeated-availability-02",
    ]
    assert duplicate.incidents[0].source_reading_ids.count(
        "s08-repeated-fire-report-identity"
    ) == 1
    assert len(state["_s08_reports"]) == 1


def test_run_change_resets_episode_state(fire_case):
    batch = load_batches(fire_case)[0]
    state = {}
    detector = FireScenario()

    first = detector.detect(batch, load_nodes(fire_case), fire_case["policy"], state)
    changed_run = batch.model_copy(
        update={
            "run_id": "fixture-s08-next-run",
            "readings": [
                reading.model_copy(update={"run_id": "fixture-s08-next-run"})
                for reading in batch.readings
            ],
        }
    )
    second = detector.detect(changed_run, load_nodes(fire_case), fire_case["policy"], state)

    assert len(first.incidents) == len(second.incidents) == 1
    assert second.incidents[0].run_id == "fixture-s08-next-run"
    assert second.incidents[0].incident_id != first.incidents[0].incident_id
    assert state["_s08_run_id"] == "fixture-s08-next-run"
    assert len(state["_s08_reports"]) == 1


def test_separate_injury_evidence_is_not_inferred_or_added_to_fire_facts():
    case = load_case("s08_fire_with_separate_injury_evidence.json")
    batch = load_batches(case)[0]
    result = _detect(case, batch=batch)

    assert len(result.incidents) == 1
    incident = result.incidents[0]
    injury_id = "s08-injury-separate-report-01"
    assert injury_id in {reading.reading_id for reading in batch.readings}
    assert injury_id not in incident.source_reading_ids
    assert not any("injur" in key.lower() for key in incident.facts)
    assert incident.source_reading_ids == [
        "s08-injury-fire-report-01",
        "s08-injury-firefighter-availability-01",
    ]
