"""The running simulation: the clock ticking, and the readings it produces.

Readings are never stored here. observed readings for any tick are calculated on demand from
(seed, tick), see sensors.py. This class only knows which tick we are at and wakes up listeners when it moves.
"""
import asyncio
import time
from datetime import timedelta

from .clock import SimClock
from .models import ClockInfo, Reading, ReadingsBatch, Topology
from .sensors import Device, SensorModel, devices_from_nodes
from .settings import TwinConfig
from .util import format_rfc3339


def sensor_domains(config: TwinConfig) -> dict[str, str]:
    """Which domain each sensor belongs to (a sensor name is only ever used by one domain)."""
    out: dict[str, str] = {}
    for dom, dcfg in config.generator.domains.items():
        for s in dcfg.sensors:
            out[s] = dom
    for role in config.generator.emergency_roles.values():
        for s in role.sensors:
            out[s] = "emergency"
    return out


class Simulation:
    def __init__(self, topology: Topology, config: TwinConfig):
        self.seed = topology.seed
        self.cfg = config.clock
        self.clock = SimClock(self.cfg.start, self.cfg.tick_seconds)
        self.devices: list[Device] = devices_from_nodes(topology.nodes, sensor_domains(config))
        self.model = SensorModel(self.seed, config.sensor_model, self.devices)
        self.node_ids = {n.node_id for n in topology.nodes}
        self.sensor_names = set(config.sensors)
        self.run_number = 1
        self.tick = 0
        self.running = False
        self._changed = asyncio.Condition()
        self.overlay = None          # containment (set by the app): says which devices are cut off from the feed

    # ------------------------------------------------------------ identity of this run
    @property
    def run_id(self) -> str:
        return f"run-{self.seed}-{self.run_number:03d}"

    # ------------------------------------------------------------ readings (pure calculation)
    def readings_at(self, tick: int, *, domain: str | None = None, node_id: str | None = None,
                    sensor: str | None = None) -> ReadingsBatch:
        run_id = self.run_id
        out: list[Reading] = []
        for d in self.devices:
            if (domain and d.domain != domain) or (node_id and d.node_id != node_id) or (sensor and d.sensor != sensor):
                continue
            if self.overlay is not None and self.overlay.is_hidden(d.device_id, tick):
                continue                 # isolated or quarantined: its data is not on the main feed
            for ch in (d.channels or (None,)):
                wobble = self.model.timing_wobble_ms(d, ch, tick)
                ts = _shift(self.clock, tick, wobble)
                rid = f"rd{tick:07d}-{d.device_id}" + (f"-{ch}" if ch else "")
                out.append(Reading(run_id=run_id, reading_id=rid, tick=tick, timestamp=ts, node_id=d.node_id,
                                   device_id=d.device_id, sensor=d.sensor, channel=ch,
                                   value=self.model.observed_value(d, ch, tick), unit=d.unit))
        return ReadingsBatch(run_id=run_id, tick=tick, time=self.clock.iso_of(tick),
                             tick_seconds=self.clock.tick_seconds, count=len(out), readings=out)

    def current(self, **filters) -> ReadingsBatch:
        return self.readings_at(self.tick, **filters)

    def clock_info(self) -> ClockInfo:
        return ClockInfo(run_id=self.run_id, tick=self.tick, time=self.clock.iso_of(self.tick),
                         tick_seconds=self.clock.tick_seconds, speed=self.cfg.speed, running=self.running)

    # ------------------------------------------------------------ moving time
    async def advance(self, n: int = 1) -> None:
        async with self._changed:
            self.tick += n
            self._changed.notify_all()

    async def reset(self) -> None:
        """A new run: new run_id, tick back to 0. (Scenario resets will call this.)"""
        async with self._changed:
            self.run_number += 1
            self.tick = 0
            self._changed.notify_all()

    async def wait_for_change(self, run_number: int, tick: int, timeout: float) -> bool:
        """Wait until the position differs from (run_number, tick). False if nothing moved in time."""
        async def _wait():
            async with self._changed:
                await self._changed.wait_for(lambda: (self.run_number, self.tick) != (run_number, tick))
        try:
            await asyncio.wait_for(_wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def run_forever(self) -> None:
        """Tick at real speed (divided by cfg.speed). Schedules against a fixed timetable, so a slow tick
        does not make every later tick late."""
        interval = self.cfg.tick_seconds / self.cfg.speed
        self.running = True
        next_at = time.monotonic() + interval
        try:
            while True:
                await asyncio.sleep(max(0.0, next_at - time.monotonic()))
                await self.advance()
                next_at += interval
        finally:
            self.running = False


def _shift(clock: SimClock, tick: int, wobble_ms: float) -> str:
    return format_rfc3339(clock.time_of(tick) + timedelta(milliseconds=wobble_ms))
