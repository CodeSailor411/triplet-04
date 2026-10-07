"""Fixed development inventory, not a working detector/decision dispatcher."""

from civis_brain.ports import Scenario
from civis_brain.scenarios.air_quality.service import AirQualityScenario
from civis_brain.scenarios.emergency.service import EmergencyScenario
from civis_brain.scenarios.power.service import PowerScenario
from civis_brain.scenarios.traffic.service import TrafficScenario
from civis_brain.scenarios.water.service import WaterScenario

SCENARIOS: tuple[Scenario, ...] = (
    TrafficScenario(), WaterScenario(), PowerScenario(), AirQualityScenario(), EmergencyScenario(),
)
