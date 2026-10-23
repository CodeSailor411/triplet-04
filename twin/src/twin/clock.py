"""The simulated clock.

Time in the city is a whole number (the tick) plus a start time. Nothing here reads the real clock:
time_of(tick) is a plain calculation, so the same tick always gives the same simulated time.
How fast ticks happen in real life is the simulation's job (sim.py), not the clock's.
"""
from datetime import datetime, timedelta

from .util import format_rfc3339


class SimClock:
    def __init__(self, start: str, tick_seconds: float):
        self.start = datetime.fromisoformat(start)          # python 3.12 reads the trailing Z
        self.tick_seconds = tick_seconds

    def time_of(self, tick: int) -> datetime:
        return self.start + timedelta(seconds=tick * self.tick_seconds)

    def iso_of(self, tick: int) -> str:
        return format_rfc3339(self.time_of(tick))
