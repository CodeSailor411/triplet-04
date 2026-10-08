import json
from pathlib import Path

import pytest

from civis_brain.contracts import Node, ReadingsBatch
from civis_brain.scenarios.power.service import PowerScenario

CASE = Path(__file__).resolve().parents[3] / "mocks/cases/power/base_case.json"


@pytest.mark.parametrize(
    "value,unit,enabled,count",
    [
        (650.0, "kW", True, 1),
        (0.0, "kW", True, 0),
        (None, "kW", True, 0),
        (650.0, "W", True, 0),
        (650.0, "kW", False, 0),
    ],
)
def test_power_threshold_evidence(value, unit, enabled, count):
    case = json.loads(CASE.read_text())
    case["batches"][0]["readings"][0].update(value=value, unit=unit)
    result = PowerScenario().detect(
        ReadingsBatch.model_validate(case["batches"][0]),
        [Node.model_validate(row) for row in case["nodes"]],
        case["policy"] | {"threshold_detection_enabled": enabled},
        {},
    )
    assert len(result.incidents) == count
    if count:
        assert "not confirmed service loss" in result.incidents[0].facts["classification"]
    else:
        assert any("POWER_EVIDENCE_UNCONFIRMED" in warning for warning in result.warnings)


def test_other_sensor_on_shared_node_has_no_power_alert():
    case = json.loads(CASE.read_text())
    case["nodes"][0]["domains"].append("air_quality")
    case["batches"][0]["readings"][0].update(sensor="pm25", unit="ug/m3")
    result = PowerScenario().detect(
        ReadingsBatch.model_validate(case["batches"][0]),
        [Node.model_validate(row) for row in case["nodes"]],
        case["policy"],
        {},
    )
    assert not result.observations and not result.incidents and not result.warnings
