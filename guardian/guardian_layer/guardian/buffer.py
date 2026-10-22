"""
Keeps a short rolling history per sensor. This is needed for:
- statistical drift checks (need past values)
- replay attack detection (need last sequence number / timestamp)
- correlation checks (need recent readings from OTHER sensors too)
"""

from collections import deque, defaultdict
from typing import Optional
from .models import SensorReading

MAX_HISTORY_PER_SENSOR = 200


class SensorBuffer:
    def __init__(self):
        self._history: dict[str, deque[SensorReading]] = defaultdict(
            lambda: deque(maxlen=MAX_HISTORY_PER_SENSOR)
        )
        self._last_sequence: dict[str, int] = {}
        self._reading_index: dict[str, SensorReading] = {}  # reading_id -> reading
        # reading_ids that have been rolled back / invalidated. Kept in the
        # history deque (for audit) but excluded from anything used to judge
        # FUTURE readings (rate-of-change baselines, correlation evidence).
        self._invalidated: set[str] = set()

    def add(self, reading: SensorReading) -> None:
        self._history[reading.sensor_id].append(reading)
        self._last_sequence[reading.sensor_id] = reading.sequence_number
        self._reading_index[reading.reading_id] = reading

    def mark_invalid(self, reading_id: str) -> bool:
        """Flag a reading as invalidated (e.g. after a rollback). Returns
        True if the reading existed and was newly marked."""
        if reading_id not in self._reading_index:
            return False
        self._invalidated.add(reading_id)
        return True

    def is_invalid(self, reading_id: str) -> bool:
        return reading_id in self._invalidated

    def history(self, sensor_id: str, include_invalid: bool = False) -> list[SensorReading]:
        hist = list(self._history.get(sensor_id, []))
        if not include_invalid:
            hist = [r for r in hist if r.reading_id not in self._invalidated]
        return hist

    def last_sequence(self, sensor_id: str) -> Optional[int]:
        return self._last_sequence.get(sensor_id)

    def get_reading(self, reading_id: str) -> Optional[SensorReading]:
        return self._reading_index.get(reading_id)

    def recent_by_type(self, sensor_type: str, since_ts: float,
                        include_invalid: bool = False) -> list[SensorReading]:
        """Used by the correlation engine: 'has any air_quality sensor moved since T?'
        Invalidated (rolled-back) readings are excluded by default so a
        rolled-back spoof can't itself count as corroborating evidence for
        some other incident later on."""
        out = []
        for hist in self._history.values():
            for r in hist:
                if not include_invalid and r.reading_id in self._invalidated:
                    continue
                if r.sensor_type == sensor_type and r.timestamp >= since_ts:
                    out.append(r)
        return out

    def is_replay_or_out_of_order(self, sensor_id: str, sequence_number: int) -> bool:
        last = self._last_sequence.get(sensor_id)
        if last is None:
            return False
        return sequence_number <= last
