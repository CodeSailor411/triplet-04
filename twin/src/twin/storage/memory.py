"""The default backend: everything in lists in memory. Gone when the Twin stops. Needs nothing installed."""
from typing import Any


class MemoryHistory:
    name = "memory"

    def __init__(self) -> None:
        self._readings: dict[tuple[str, str], dict[str, Any]] = {}      # (run_id, reading_id) -> row
        self._events: dict[tuple[str, str], dict[str, Any]] = {}        # (run_id, event_id) -> line

    def write_readings(self, rows: list[dict[str, Any]]) -> None:
        for r in rows:
            self._readings.setdefault((r["run_id"], r["reading_id"]), dict(r))     # setdefault = skip if present

    def write_events(self, rows: list[dict[str, Any]]) -> None:
        for e in rows:
            self._events.setdefault((e["run_id"], e["event_id"]), dict(e))

    def query_readings(self, run_id, *, device_id=None, from_tick=None, to_tick=None):
        out = [r for (rid, _), r in self._readings.items() if rid == run_id
               and (device_id is None or r["device_id"] == device_id)
               and (from_tick is None or r["tick"] >= from_tick) and (to_tick is None or r["tick"] <= to_tick)]
        return sorted(out, key=lambda r: (r["tick"], r["reading_id"]))

    def query_events(self, run_id, *, event_type=None):
        out = [e for (rid, _), e in self._events.items() if rid == run_id and (event_type is None or e["event_type"] == event_type)]
        return sorted(out, key=lambda e: e["event_id"])

    def close(self) -> None:
        pass
