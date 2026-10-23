"""The history store: where the Twin keeps what happened, so it can be asked about later.

Why an interface (a Protocol = a list of methods any backend must have): the Twin must run with NOTHING installed
(R1: each layer runs alone, and the demo has "nothing installed on stage"). So the default backend is `memory`.
TimescaleDB is an option that is switched on in config. The rest of the Twin only talks to this list of methods,
so it does not care which one is behind it.

What goes in (and what never does):
  * readings: what the live feed showed (the REPORTED value, after faults and containment). One row per reading.
  * events:   the Twin's own run-log lines (actions, containment, scenarios, faulted readings).
  * NEVER the true value. The true value is private to the Twin. There is no column for it, on purpose.

Every write is safe to repeat: a row that is already there is skipped, not duplicated. That matters because a writer
that was cut off in the middle cannot know if its last batch arrived, so it just sends it again.
"""
from typing import Any, Protocol


class HistoryStore(Protocol):
    name: str

    def write_readings(self, rows: list[dict[str, Any]]) -> None:
        """Store readings (dicts from Reading.model_dump()). Rows already stored are skipped. Raises on failure."""

    def write_events(self, rows: list[dict[str, Any]]) -> None:
        """Store run-log lines (the dicts the run log writes to its JSONL file). Same rules as write_readings."""

    def query_readings(self, run_id: str, *, device_id: str | None = None, from_tick: int | None = None,
                       to_tick: int | None = None) -> list[dict[str, Any]]:
        """Readings of one run, oldest first. Tick bounds are inclusive."""

    def query_events(self, run_id: str, *, event_type: str | None = None) -> list[dict[str, Any]]:
        """Events of one run, in order."""

    def close(self) -> None: ...
