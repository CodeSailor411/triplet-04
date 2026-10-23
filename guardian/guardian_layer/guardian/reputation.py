"""
Layer E: reputation / trust history per device.

A sensor that's been flagged repeatedly should start from a lower baseline
even if today's single reading looks fine. A sensor with a clean history
should get some benefit of the doubt. Trust decays back toward neutral
over time if no new flags come in -- a sensor isn't punished forever for
one old incident.
"""

import time
from dataclasses import dataclass, field


DECAY_HALF_LIFE_SECONDS = 3600.0  # 1 hour: flags matter less as they age
MAX_TRACKED_FLAGS = 50


@dataclass
class SensorReputation:
    sensor_id: str
    flags: list[float] = field(default_factory=list)  # timestamps of past flags
    quarantined: bool = False
    isolated: bool = False


class ReputationStore:
    def __init__(self):
        self._store: dict[str, SensorReputation] = {}

    def _get_or_create(self, sensor_id: str) -> SensorReputation:
        if sensor_id not in self._store:
            self._store[sensor_id] = SensorReputation(sensor_id=sensor_id)
        return self._store[sensor_id]

    def record_flag(self, sensor_id: str) -> None:
        rep = self._get_or_create(sensor_id)
        rep.flags.append(time.time())
        if len(rep.flags) > MAX_TRACKED_FLAGS:
            rep.flags = rep.flags[-MAX_TRACKED_FLAGS:]

    def recent_flags(self, sensor_id: str, now: float | None = None) -> float:
        """Returns a decayed flag count -- recent flags count close to 1.0,
        old flags count close to 0."""
        rep = self._store.get(sensor_id)
        if not rep or not rep.flags:
            return 0.0
        now = now or time.time()
        total = 0.0
        for ts in rep.flags:
            age = now - ts
            weight = 0.5 ** (age / DECAY_HALF_LIFE_SECONDS)
            total += weight
        return total

    def set_quarantined(self, sensor_id: str, value: bool = True) -> None:
        self._get_or_create(sensor_id).quarantined = value

    def set_isolated(self, sensor_id: str, value: bool = True) -> None:
        self._get_or_create(sensor_id).isolated = value

    def is_contained(self, sensor_id: str) -> bool:
        rep = self._store.get(sensor_id)
        return bool(rep and (rep.quarantined or rep.isolated))

    def get(self, sensor_id: str) -> SensorReputation:
        return self._get_or_create(sensor_id)
