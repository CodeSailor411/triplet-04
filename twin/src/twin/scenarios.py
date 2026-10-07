"""Scenario engine: starts attacks on purpose and keeps a record of them.

Three attacks (the ones the triplet decided to fake first):
  fake_reading   the sensor REPORTS a made-up value. The true value does not change (T5: reports 180 cm, real level is ~40).
  stuck_sensor   the sensor keeps repeating the last value it reported before the fault.
  replay_exact   the sensor re-sends an OLD reading as it was: same reading_id, same old tick and time (exact duplicate).
                 (The second replay mode, recycled values under a fresh id, comes on 28 Oct.)

How it works: readings are calculated from (seed, tick), they are never stored. A fault is just a record
"device X, from tick A to tick B, does Y". When the Twin builds a reading it asks the fault book if one applies.
So the same seed plus the same faults gives the same run, and a fault can never change a reading from before it started.

Only the scenario key can call this (see auth.py). Faults change what is REPORTED. Nothing here touches the true values.
"""
import math
import threading
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from .actions import BadRequest
from .sensors import Device
from .sim import Simulation

MAX_LAG_TICKS = 600
MAX_DELAY_TICKS = 3600


# ---------------------------------------------------------------------- what a fault is
@dataclass
class Fault:
    fault_id: str
    scenario_id: str
    kind: Literal["fake_reading", "stuck_sensor", "replay_exact"]
    device_id: str
    channel: str | None            # None = every channel of the device
    start_tick: int                # first tick that is affected
    end_tick: int | None           # first tick that is NOT affected any more (None = until stopped)
    value: float | None = None     # fake_reading only
    lag_ticks: int | None = None   # replay_exact only

    def covers(self, device_id: str, channel: str | None, tick: int) -> bool:
        return (self.device_id == device_id and (self.channel is None or self.channel == channel)
                and self.start_tick <= tick and (self.end_tick is None or tick < self.end_tick))


# ---------------------------------------------------------------------- shapes the tool hands out
class FaultInfo(BaseModel):
    fault_id: str
    kind: str
    device_id: str
    channel: str | None
    start_tick: int
    start_time: str
    end_tick: int | None
    value: float | None = None
    lag_ticks: int | None = None


class ScenarioInfo(BaseModel):
    name: str
    description: str
    params: dict[str, str]         # parameter -> short explanation with the default


class ScenarioResult(BaseModel):
    status: Literal["started", "stopped", "reset", "listed"]
    name: str
    scenario_id: str | None = None
    run_id: str
    tick: int
    time: str
    faults: list[FaultInfo] = []
    scenarios: list[ScenarioInfo] = []


COMMON = {"device_id": "which sensor (see list_nodes)", "channel": "only for sensors with channels, else leave out",
          "delay_ticks": "ticks until the fault starts, at least 1 (default 2)",
          "duration_ticks": "how long it lasts in ticks (default: until stopped)"}

SCENARIOS: dict[str, tuple[str, dict[str, str], dict[str, Any]]] = {
    "fake_reading": ("The sensor reports a made-up value. The true value does not change.",
                     {**COMMON, "value": "the fake value (default 180)"},
                     {"device_id": "WAT-01.water_level", "value": 180.0}),
    "stuck_sensor": ("The sensor keeps repeating the last value it reported before the fault.",
                     COMMON, {"device_id": "WAT-02.water_level"}),
    "replay_exact": ("The sensor re-sends an old reading exactly as it was (same reading_id, old time).",
                     {**COMMON, "lag_ticks": "how many ticks old the replayed reading is (default 30)"},
                     {"device_id": "WAT-03.water_level", "lag_ticks": 30}),
}
CONTROL = {"list": "Say which scenarios exist.", "stop": "Stop a scenario: params {scenario_id}. Its faults end after the current tick.",
           "reset": "Start a new run: new run_id, clock back to 0, every fault, cut-off device and used token forgotten."}


# ---------------------------------------------------------------------- the book
class ScenarioBook:
    def __init__(self, sim: Simulation):
        self.sim = sim
        self.devices: dict[str, Device] = {d.device_id: d for d in sim.devices}
        self._lock = threading.RLock()
        self._run = sim.run_number
        self._reset_state()

    def _reset_state(self) -> None:
        self.faults: list[Fault] = []
        self.history: list[dict[str, Any]] = []      # what happened, in order. The log writer (9 Oct) reads this.
        self._n_scenario = 0
        self._n_fault = 0

    def _sync(self) -> None:
        if self._run != self.sim.run_number:
            self._run = self.sim.run_number
            self._reset_state()

    # ------------------------------------------------------------------ asked by the simulation and containment
    def fault_at(self, device_id: str, channel: str | None, tick: int) -> Fault | None:
        with self._lock:
            self._sync()
            for f in self.faults:                    # at most one can cover a (device, channel, tick): overlaps are refused
                if f.covers(device_id, channel, tick):
                    return f
            return None

    def is_faulty(self, device_id: str, channel: str | None, tick: int) -> bool:
        return self.fault_at(device_id, channel, tick) is not None

    # ------------------------------------------------------------------ the one entry point
    async def run(self, name: str, params: dict[str, Any] | None) -> ScenarioResult:
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise BadRequest("INVALID_PARAMS", "params must be an object like {\"device_id\": \"WAT-01.water_level\"}.")
        if name == "reset":
            self._only(params, set())
            await self.sim.reset()
            with self._lock:
                self._sync()
                return self._result("reset", name)
        with self._lock:
            self._sync()
            if name == "list":
                self._only(params, set())
                return self._result("listed", name, scenarios=[ScenarioInfo(name=n, description=d, params=p)
                                                              for n, (d, p, _) in SCENARIOS.items()]
                                    + [ScenarioInfo(name=n, description=d, params={}) for n, d in CONTROL.items()])
            if name == "stop":
                return self._stop(params)
            if name not in SCENARIOS:
                raise BadRequest("UNKNOWN_SCENARIO", f"'{name}' is not a scenario. Known: "
                                 f"{', '.join(list(SCENARIOS) + list(CONTROL))}.")
            return self._start(name, params)

    # ------------------------------------------------------------------ start
    def _start(self, name: str, params: dict[str, Any]) -> ScenarioResult:
        _, allowed, defaults = SCENARIOS[name]
        self._only(params, set(allowed))
        p = {**defaults, **params}
        d = self._device(p["device_id"])
        channel = self._channel(d, p.get("channel"))
        delay = self._int(p, "delay_ticks", 2, 1, MAX_DELAY_TICKS)
        duration = self._int(p, "duration_ticks", None, 1, 10_000_000)
        start = self.sim.tick + delay                  # never in the past: readings already sent stay as they were
        end = None if duration is None else start + duration
        value = lag = None
        if name == "fake_reading":
            value = self._number(p, "value")
        elif name == "replay_exact":
            lag = self._int(p, "lag_ticks", 30, 1, MAX_LAG_TICKS)
            if start - lag < 0:
                raise BadRequest("START_TOO_EARLY", f"A replay with lag_ticks={lag} needs {lag} ticks of history before it "
                                 f"starts, but it would start at tick {start}. Wait, use a bigger delay_ticks, or a smaller lag_ticks.")
        self._refuse_overlap(d.device_id, channel, start, end)
        self._n_scenario += 1
        self._n_fault += 1
        sid = f"sc-{self._n_scenario:04d}"
        fault = Fault(fault_id=f"f-{self._n_fault:04d}", scenario_id=sid, kind=name, device_id=d.device_id, channel=channel,
                      start_tick=start, end_tick=end, value=value, lag_ticks=lag)
        self.faults.append(fault)
        res = self._result("started", name, scenario_id=sid, faults=[fault])
        self.history.append({"tick": res.tick, "time": res.time, "event": "scenario_started", "name": name,
                             "scenario_id": sid, "faults": [f.model_dump() for f in res.faults]})
        return res

    # ------------------------------------------------------------------ stop
    def _stop(self, params: dict[str, Any]) -> ScenarioResult:
        self._only(params, {"scenario_id"})
        sid = params.get("scenario_id")
        mine = [f for f in self.faults if f.scenario_id == sid]
        if not isinstance(sid, str) or not mine:
            raise BadRequest("UNKNOWN_SCENARIO_ID", f"No scenario with id {sid!r} in this run. Ids look like sc-0001.")
        end_now = self.sim.tick + 1                        # the reading for the current tick may already be out
        for f in mine:
            if f.end_tick is None or f.end_tick > end_now:
                f.end_tick = max(end_now, f.start_tick)
        res = self._result("stopped", "stop", scenario_id=sid, faults=mine)
        self.history.append({"tick": res.tick, "time": res.time, "event": "scenario_stopped", "scenario_id": sid,
                             "faults": [f.model_dump() for f in res.faults]})
        return res

    # ------------------------------------------------------------------ checks
    @staticmethod
    def _only(params: dict[str, Any], allowed: set[str]) -> None:
        extra = sorted(set(params) - allowed)
        if extra:
            raise BadRequest("UNKNOWN_PARAM", f"Unknown parameter(s): {', '.join(extra)}. Allowed: "
                             f"{', '.join(sorted(allowed)) or 'none'}.")

    def _device(self, device_id: Any) -> Device:
        if not isinstance(device_id, str) or device_id not in self.devices:
            raise BadRequest("UNKNOWN_DEVICE", f"{device_id!r} is not a device. Device ids are in list_nodes (sensors[].device_id).")
        return self.devices[device_id]

    @staticmethod
    def _channel(d: Device, channel: Any) -> str | None:
        if channel is None:
            return None
        if channel not in d.channels:
            have = ", ".join(d.channels) if d.channels else "none (this sensor has no channels)"
            raise BadRequest("UNKNOWN_CHANNEL", f"{d.device_id} has no channel {channel!r}. Channels: {have}.")
        return channel

    @staticmethod
    def _int(p: dict[str, Any], key: str, default: int | None, lo: int, hi: int) -> int | None:
        v = p.get(key, default)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise BadRequest("INVALID_PARAM", f"{key} must be a whole number from {lo} to {hi}.")
        return v

    @staticmethod
    def _number(p: dict[str, Any], key: str) -> float:
        v = p.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e9:
            raise BadRequest("INVALID_PARAM", f"{key} must be a normal number (not NaN, not infinite, at most 1e9).")
        return float(v)

    def _refuse_overlap(self, device_id: str, channel: str | None, start: int, end: int | None) -> None:
        for f in self.faults:
            same_channel = f.channel is None or channel is None or f.channel == channel
            overlaps = (f.end_tick is None or start < f.end_tick) and (end is None or f.start_tick < end)
            if f.device_id == device_id and same_channel and overlaps:
                raise BadRequest("FAULT_ALREADY_ACTIVE", f"{device_id} already has fault {f.fault_id} ({f.kind}) in that time. "
                                 f"Stop scenario {f.scenario_id} first.")

    # ------------------------------------------------------------------ answers
    def _result(self, status: str, name: str, *, scenario_id: str | None = None, faults: list[Fault] | None = None,
                scenarios: list[ScenarioInfo] | None = None) -> ScenarioResult:
        tick = self.sim.tick
        return ScenarioResult(
            status=status, name=name, scenario_id=scenario_id, run_id=self.sim.run_id, tick=tick,
            time=self.sim.clock.iso_of(tick), scenarios=scenarios or [],
            faults=[FaultInfo(fault_id=f.fault_id, kind=f.kind, device_id=f.device_id, channel=f.channel,
                              start_tick=f.start_tick, start_time=self.sim.clock.iso_of(f.start_tick), end_tick=f.end_tick,
                              value=f.value, lag_ticks=f.lag_ticks) for f in (faults or [])])
