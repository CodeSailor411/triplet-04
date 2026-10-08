import json
from pathlib import Path

import pytest

from civis_brain.contracts import Node, ReadingsBatch
from civis_brain.scenarios.air_quality.service import AirQualityScenario

CASE = Path(__file__).resolve().parents[3] / "mocks/cases/air_quality/base_case.json"


def fixture():
    case = json.loads(CASE.read_text())
    return case, [Node.model_validate(row) for row in case["nodes"]]


def test_two_distinct_ticks_and_preserved_evidence():
    case, nodes = fixture()
    detector, state = AirQualityScenario(), {}
    first, second = [ReadingsBatch.model_validate(raw) for raw in case["batches"]]
    assert not detector.detect(first, nodes, case["policy"], state).incidents
    assert not detector.detect(first, nodes, case["policy"], state).incidents
    incident = detector.detect(second, nodes, case["policy"], state).incidents[0]
    assert incident.source_reading_ids == ["AQ-01-1", "AQ-01-2"]
    assert detector.detect(second, nodes, case["policy"], state).incidents[0] == incident
    assert incident.domains == ["air_quality", "emergency"]
    assert incident.kind == "air_pollution"


@pytest.mark.parametrize("value,unit", [(0.0, "ug/m3"), (None, "ug/m3"), (100.0, "mg/m3")])
def test_baseline_null_or_wrong_unit_breaks_streak(value, unit):
    case, nodes = fixture()
    detector, state = AirQualityScenario(), {}
    first, second = [ReadingsBatch.model_validate(raw) for raw in case["batches"]]
    detector.detect(first, nodes, case["policy"], state)
    second.readings[0].value, second.readings[0].unit = value, unit
    assert not detector.detect(second, nodes, case["policy"], state).incidents


def test_new_run_resets_persistence():
    case, nodes = fixture()
    detector, state = AirQualityScenario(), {}
    detector.detect(ReadingsBatch.model_validate(case["batches"][0]), nodes, case["policy"], state)
    second = ReadingsBatch.model_validate(case["batches"][1])
    second.run_id = second.readings[0].run_id = "next-run"
    assert not detector.detect(second, nodes, case["policy"], state).incidents
