"""
Layer C: cross-source correlation.

Spoofing ONE sensor is easy. Spoofing every physically-correlated signal
consistently is hard. This module checks: if a reading looks like it
signals an incident, did the OTHER signals that incident should produce
actually move within a plausible time window?

Fill in / tune this table with your City Brain and Twin teammates so
everyone agrees what "fire" etc. structurally means.
"""

from dataclasses import dataclass
from .buffer import SensorBuffer

# incident_type -> list of (corroborating sensor_type, expected direction, window_seconds)
# direction: "increase" | "decrease" | "any_change"
EVENT_CORRELATIONS: dict[str, list[tuple[str, str, float]]] = {
    "fire": [
        ("air_quality", "increase", 30.0),
        ("emergency_call", "increase", 60.0),
        ("power_load", "any_change", 45.0),
    ],
    "flood": [
        ("water_level", "increase", 20.0),
        ("power_load", "any_change", 45.0),
        ("traffic_cam", "increase", 60.0),  # congestion from road closures
    ],
    "accident": [
        ("traffic_cam", "increase", 15.0),
        ("emergency_call", "increase", 30.0),
    ],
    "traffic_jam": [
        ("traffic_cam", "increase", 10.0),
        ("air_quality", "increase", 60.0),  # idling engines
    ],
}


@dataclass
class CorrelationResult:
    expected: bool          # was correlation expected at all for this incident type?
    found: bool             # did we find corroborating evidence?
    strength: float         # 0-1, how strong was the corroboration
    checked: list[str]      # which sensor types were checked


def check_correlation(incident_type: str, event_timestamp: float,
                       buffer: SensorBuffer) -> CorrelationResult:
    rules = EVENT_CORRELATIONS.get(incident_type)
    if not rules:
        return CorrelationResult(expected=False, found=True, strength=1.0, checked=[])

    hits = 0
    checked_types = []
    for sensor_type, direction, window in rules:
        checked_types.append(sensor_type)

        # Corroborating signals can arrive slightly BEFORE the primary signal
        # (e.g. smoke/air-quality often precedes an explicit fire trigger) or
        # AFTER it (e.g. emergency calls follow), so we look both ways.
        # We pull a wide slice of history so we have a BASELINE to compare
        # against -- a single in-window reading has no "before" value of its
        # own to diff against, which was a bug in an earlier version of this
        # check (it silently treated a lone reading as "no change").
        all_readings = buffer.recent_by_type(sensor_type, since_ts=event_timestamp - 3600.0)
        all_readings.sort(key=lambda r: r.timestamp)

        window_start = event_timestamp - window
        window_end = event_timestamp + window
        baseline = [r for r in all_readings if r.timestamp < window_start]
        in_window = [r for r in all_readings if window_start <= r.timestamp <= window_end]

        if not in_window:
            continue  # nothing from this sensor type near the event at all

        if direction == "any_change":
            hits += 1
            continue

        # Compare the extreme value seen in-window against a baseline level.
        # If there's no baseline yet (cold start), fall back to the earliest
        # in-window reading as a rough reference point.
        baseline_value = (sum(r.value for r in baseline) / len(baseline)) if baseline \
            else in_window[0].value

        if direction == "increase":
            peak = max(r.value for r in in_window)
            if peak > baseline_value:
                hits += 1
        elif direction == "decrease":
            trough = min(r.value for r in in_window)
            if trough < baseline_value:
                hits += 1

    strength = hits / len(rules) if rules else 1.0
    return CorrelationResult(
        expected=True,
        found=strength > 0.0,
        strength=strength,
        checked=checked_types,
    )
