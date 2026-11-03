"""Fixed scenario inventory and delivered implementation IDs."""

from civis_brain.ports import Scenario
from civis_brain.scenarios.air_quality.service import AirQualityScenario
from civis_brain.scenarios.emergency.fire import FireScenario
from civis_brain.scenarios.emergency.service import EmergencyScenario
from civis_brain.scenarios.power.service import PowerScenario
from civis_brain.scenarios.traffic.accident import RoadAccidentScenario
from civis_brain.scenarios.traffic.service import TrafficScenario
from civis_brain.scenarios.water.low_water import LowWaterScenario
from civis_brain.scenarios.water.service import WaterScenario

SCENARIOS: tuple[Scenario, ...] = (
    TrafficScenario(), WaterScenario(), PowerScenario(), AirQualityScenario(), EmergencyScenario(), RoadAccidentScenario(), LowWaterScenario(), FireScenario(),
)

IMPLEMENTED_SCENARIOS = ("S01", "S02", "S03", "S04", "S05", "S06", "S07")

# S08 detection is delivered; its response remains under member development.
DETECTION_ONLY_SCENARIOS = ("S08",)
