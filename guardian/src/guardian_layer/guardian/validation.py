"""
Layer A: schema/protocol sanity (handled mostly in main.py + security.py)
Layer B: physical plausibility -- is this value physically possible,
         and is it consistent with the sensor's own recent history?
"""

from statistics import mean, pstdev
from .models import SensorReading

# Hardcoded physical bounds per sensor type. Tune these to your Twin's
# actual simulated ranges -- these are illustrative placeholders.
BOUNDS = {
    "traffic_cam":     {"min": 0.0,    "max": 100.0,  "unit_hint": "% congestion"},
    "water_level":     {"min": 0.0,    "max": 10.0,   "unit_hint": "meters"},
    "power_load":      {"min": 0.0,    "max": 5000.0, "unit_hint": "kW"},
    "air_quality":     {"min": 0.0,    "max": 500.0,  "unit_hint": "AQI"},
    "emergency_call":  {"min": 0.0,    "max": 1000.0, "unit_hint": "calls/min"},
}

# Max plausible change per second, per sensor type -- catches "teleporting"
# values that jump further/faster than physically possible.
MAX_RATE_OF_CHANGE = {
    "traffic_cam": 20.0,
    "water_level": 0.5,
    "power_load": 500.0,
    "air_quality": 50.0,
    "emergency_call": 100.0,
}

Z_SCORE_THRESHOLD = 3.0  # flag if reading is more than 3 std-devs from recent mean


def violates_bounds(reading: SensorReading) -> bool:
    b = BOUNDS.get(reading.sensor_type)
    if b is None:
        return False  # unknown sensor type -- can't bound-check, don't block
    return not (b["min"] <= reading.value <= b["max"])


def violates_rate_of_change(reading: SensorReading, history: list[SensorReading]) -> bool:
    if not history:
        return False
    prev = history[-1]
    dt = max(reading.timestamp - prev.timestamp, 0.001)  # avoid div-by-zero
    rate = abs(reading.value - prev.value) / dt
    max_rate = MAX_RATE_OF_CHANGE.get(reading.sensor_type)
    if max_rate is None:
        return False
    return rate > max_rate


def is_statistical_outlier(reading: SensorReading, history: list[SensorReading]) -> bool:
    """Simple z-score check against recent history. Needs a few points to be meaningful."""
    if len(history) < 5:
        return False
    values = [r.value for r in history[-20:]]
    mu = mean(values)
    sigma = pstdev(values) or 1e-6  # avoid div-by-zero on constant history
    z = abs(reading.value - mu) / sigma
    return z > Z_SCORE_THRESHOLD
