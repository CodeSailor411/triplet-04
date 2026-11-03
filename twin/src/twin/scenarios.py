"""Scenario engine: starts attacks on purpose and keeps a record of them.

Three attacks (the ones the triplet decided to fake first):
  fake_reading   the sensor REPORTS a made-up value. The true value does not change (T5: reports 180 cm, real level is ~40).
  stuck_sensor   the sensor keeps repeating the last value it reported before the fault.
  replay_exact   the sensor re-sends an OLD reading as it was: same reading_id, same old tick and time (exact duplicate).
                 (The second replay mode, recycled values under a fresh id, comes on 28 Oct.)

How it works: readings are calculated from (seed, tick), they are never stored. A fault is just a record
"device X, from tick A to tick B, does Y". When the Twin builds a reading it asks the fault book if one applies.
So the same seed plus the same faults gives the same run, and a fault can never change a reading from before it started.

One real event (added 2 Nov):
  real_jam       a REAL traffic jam. Unlike the attacks above it moves the TRUE value of the traffic sensors at one node
                 (and, weaker, at its traffic neighbours): it builds up over a few ticks, holds, then fades and ends by itself.
                 Every sensor at the node then reports what is really there. The jam does not react to `actuate` (nothing in
                 the city does yet), so a signal change does not ease it.

Only the scenario key can call this (see auth.py). Faults change what is REPORTED. Only `real_jam` changes true values,
and only by a fixed rule that depends on (seed, device, tick, the incident record), so the same seed plus the same
scenarios still gives the same run.
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
# A real jam pulls the true value of these sensors towards these numbers (at the jam's node: all the way at the peak).
# congestion_index 90 sits above the Brain's S01 rule (index of at least 80 on two ticks in a row), so noise cannot hide it.
JAM_TARGETS = {"congestion_index": 90.0, "vehicle_count": 120.0, "avg_speed": 8.0}
JAM_DEFAULTS = {"ramp_ticks": 10, "hold_ticks": 40, "fade_ticks": 10, "spread": 0.35}


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


@dataclass
class Incident:
    """A real event. `weights` says how strongly each node is hit: 1.0 at the centre, `spread` at its traffic neighbours."""
    incident_id: str
    scenario_id: str
    kind: Literal["real_jam"]
    node_id: str                   # the centre of the jam
    weights: dict[str, float]      # node_id -> share of the full effect (centre 1.0, neighbours = spread)
    start_tick: int                # first tick that is affected
    ramp_ticks: int                # ticks to build up to the peak
    hold_ticks: int                # ticks at the peak
    fade_ticks: int                # ticks to fade out again
    spread: float = 0.0            # the share of the jam that reaches traffic neighbours (what the caller asked for)
    stop_tick: int | None = None   # set by `stop`: first tick that is NOT affected any more

    @property
    def natural_end(self) -> int:
        return self.start_tick + self.ramp_ticks + self.hold_ticks + self.fade_ticks

    @property
    def end_tick(self) -> int:
        return self.natural_end if self.stop_tick is None else min(self.natural_end, self.stop_tick)

    def level(self, tick: int) -> float:
        """0 before the start and after the end, rising in `ramp_ticks` steps to 1, 1 while holding, falling to 0 in the fade."""
        k = tick - self.start_tick
        if k < 0 or tick >= self.end_tick:
            return 0.0
        if k < self.ramp_ticks:
            return (k + 1) / self.ramp_ticks
        if k < self.ramp_ticks + self.hold_ticks:
            return 1.0
        j = k - self.ramp_ticks - self.hold_ticks
        return (self.fade_ticks - j) / (self.fade_ticks + 1)


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


class IncidentInfo(BaseModel):
    incident_id: str
    kind: str
    node_id: str
    affected_nodes: list[str]        # the centre first, then its traffic neighbours
    spread: float
    start_tick: int
    start_time: str
    ramp_ticks: int
    hold_ticks: int
    fade_ticks: int
    end_tick: int                    # first tick that is no longer affected


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
    incidents: list[IncidentInfo] = []
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
SCENARIOS["real_jam"] = ("A REAL traffic jam at one node (and a weaker one next to it): the true value moves, it builds up, holds and ends by itself.",
                         {"node_id": "a traffic node (default: the first one that carries a signal, SH-05)",
                          "delay_ticks": "ticks until the jam starts, at least 1 (default 2)",
                          "ramp_ticks": "ticks to build up to the peak (default 10)",
                          "hold_ticks": "ticks at the peak (default 40)",
                          "fade_ticks": "ticks to fade out (default 10)",
                          "spread": "share of the jam that reaches traffic neighbours, 0 to 1 (default 0.35)"},
                         {})
CONTROL = {"list": "Say which scenarios exist.", "stop": "Stop a scenario: params {scenario_id}. Its faults end after the current tick.",
           "reset": "Start a new run: new run_id, clock back to 0, every fault, cut-off device and used token forgotten."}


# ---------------------------------------------------------------------- the book
class ScenarioBook:
    def __init__(self, sim: Simulation):
        self.sim = sim
        self.devices: dict[str, Device] = {d.device_id: d for d in sim.devices}
        self._lock = threading.RLock()
        self.recorder = None                        # set by the app: the run log
        self._run = sim.run_number
        self._node_devices: dict[str, list[Device]] = {}
        for d in sim.devices:
            self._node_devices.setdefault(d.node_id, []).append(d)
        sim.model.incident_source = self            # the sensor model asks us for real incidents
        self._reset_state()

    def _reset_state(self) -> None:
        self.incidents: list[Incident] = []
        self._n_incident = 0
        self.faults: list[Fault] = []
        self._event_ids: dict[str, str] = {}         # scenario_id -> event_id of its "started" line in the run log
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

    def active_faults(self, tick: int) -> list[Fault]:
        with self._lock:
            self._sync()
            return [f for f in self.faults if f.start_tick <= tick and (f.end_tick is None or tick < f.end_tick)]

    def incident_effect(self, device_id: str, channel: str | None, tick: int) -> tuple[float, float] | None:
        """Asked by the sensor model for every true value: (weight, target) if a real incident pulls this device now."""
        with self._lock:
            self._sync()
            if not self.incidents:
                return None
            d = self.devices.get(device_id)
            target = JAM_TARGETS.get(d.sensor) if d is not None else None
            if target is None:
                return None
            for inc in self.incidents:                # overlaps on one node are refused, so at most one can apply
                share = inc.weights.get(d.node_id)
                if share:
                    w = share * inc.level(tick)
                    if w > 0:
                        return w, target
            return None

    def active_incidents(self, tick: int) -> list[Incident]:
        with self._lock:
            self._sync()
            return [i for i in self.incidents if i.start_tick <= tick < i.end_tick]

    def incident_devices(self, inc: Incident) -> list[Device]:
        """The sensors a real jam moves: the jam sensors of every affected node."""
        return [d for node in inc.weights for d in self._node_devices.get(node, []) if d.sensor in JAM_TARGETS]

    def event_id_of(self, scenario_id: str) -> str | None:
        with self._lock:
            return self._event_ids.get(scenario_id)

    # ------------------------------------------------------------------ the one entry point
    async def run(self, name: str, params: dict[str, Any] | None) -> ScenarioResult:
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise BadRequest("INVALID_PARAMS", "params must be an object like {\"device_id\": \"WAT-01.water_level\"}.")
        if name == "reset":
            self._only(params, set())
            if self.recorder is not None:
                self.recorder.end_run()                      # close the old run's log before the run id changes
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
        if name == "real_jam":
            return self._start_jam(params)
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
        if self.recorder is not None:
            eid = self.recorder.record("scenario", {"phase": "started", "scenario_id": sid, "name": name,
                                                    "params": {k: v for k, v in params.items()},
                                                    "faults": [f.model_dump() for f in res.faults]})
            if eid:
                self._event_ids[sid] = eid
        return res

    # ------------------------------------------------------------------ start of a real jam
    def _traffic_nodes(self) -> list[str]:
        return sorted({d.node_id for d in self.devices.values() if d.sensor == "congestion_index"})

    def _default_jam_node(self) -> str:
        """The first traffic node that carries a signal (the same node the stand-in Brain watches), else the first traffic node."""
        traffic = self._traffic_nodes()
        with_signal = [n for n in traffic if "set_signal_plan" in self.sim.actuators.get(n, [])]
        return (with_signal or traffic or [""])[0]

    def _start_jam(self, params: dict[str, Any]) -> ScenarioResult:
        _, allowed, _ = SCENARIOS["real_jam"]
        self._only(params, set(allowed))
        traffic = self._traffic_nodes()
        if not traffic:
            raise BadRequest("NO_TRAFFIC_NODES", "This city has no traffic node with a congestion_index sensor.")
        node = params.get("node_id", self._default_jam_node())
        if not isinstance(node, str) or node not in traffic:
            raise BadRequest("UNKNOWN_NODE", f"{node!r} is not a traffic node with a congestion_index sensor. Traffic nodes: "
                             f"{', '.join(traffic)}.")
        delay = self._int(params, "delay_ticks", 2, 1, MAX_DELAY_TICKS)
        ramp = self._int(params, "ramp_ticks", JAM_DEFAULTS["ramp_ticks"], 1, 600)
        hold = self._int(params, "hold_ticks", JAM_DEFAULTS["hold_ticks"], 0, 3600)
        fade = self._int(params, "fade_ticks", JAM_DEFAULTS["fade_ticks"], 1, 600)
        spread = params.get("spread", JAM_DEFAULTS["spread"])
        if isinstance(spread, bool) or not isinstance(spread, (int, float)) or not math.isfinite(spread) or not 0 <= spread <= 1:
            raise BadRequest("INVALID_PARAM", "spread must be a number from 0 to 1.")
        weights = {node: 1.0}
        if spread > 0:
            for other in sorted(self.sim.links.get(node, [])):        # the jam spills over to traffic nodes next to it
                if other in traffic and other != node:
                    weights[other] = float(spread)
        start = self.sim.tick + delay                   # never in the past: readings already sent stay as they were
        end = start + ramp + hold + fade
        for inc in self.incidents:                      # one jam at a time on any node they share
            if set(inc.weights) & set(weights) and start < inc.end_tick and inc.start_tick < end:
                raise BadRequest("INCIDENT_ALREADY_ACTIVE", f"Real incident {inc.incident_id} already covers "
                                 f"{', '.join(sorted(set(inc.weights) & set(weights)))} in that time. Stop scenario "
                                 f"{inc.scenario_id} first.")
        self._n_scenario += 1
        self._n_incident += 1
        sid = f"sc-{self._n_scenario:04d}"
        inc = Incident(incident_id=f"inc-{self._n_incident:04d}", scenario_id=sid, kind="real_jam", node_id=node, weights=weights,
                       start_tick=start, ramp_ticks=ramp, hold_ticks=hold, fade_ticks=fade, spread=float(spread))
        self.incidents.append(inc)
        res = self._result("started", "real_jam", scenario_id=sid, incidents=[inc])
        info = [i.model_dump() for i in res.incidents]
        self.history.append({"tick": res.tick, "time": res.time, "event": "scenario_started", "name": "real_jam",
                             "scenario_id": sid, "faults": [], "incidents": info})
        if self.recorder is not None:
            eid = self.recorder.record("scenario", {"phase": "started", "scenario_id": sid, "name": "real_jam",
                                                    "params": dict(params), "faults": [], "incidents": info})
            if eid:
                self._event_ids[sid] = eid
        return res

    # ------------------------------------------------------------------ stop
    def _stop(self, params: dict[str, Any]) -> ScenarioResult:
        self._only(params, {"scenario_id"})
        sid = params.get("scenario_id")
        mine = [f for f in self.faults if f.scenario_id == sid]
        jams = [i for i in self.incidents if i.scenario_id == sid]
        if not isinstance(sid, str) or not (mine or jams):
            raise BadRequest("UNKNOWN_SCENARIO_ID", f"No scenario with id {sid!r} in this run. Ids look like sc-0001.")
        end_now = self.sim.tick + 1                        # the reading for the current tick may already be out
        for f in mine:
            if f.end_tick is None or f.end_tick > end_now:
                f.end_tick = max(end_now, f.start_tick)
        for i in jams:                                     # a stopped jam ends at once (no fade): a stop is a control, not weather
            if i.end_tick > end_now:
                i.stop_tick = max(end_now, i.start_tick)
        res = self._result("stopped", "stop", scenario_id=sid, faults=mine, incidents=jams)
        self.history.append({"tick": res.tick, "time": res.time, "event": "scenario_stopped", "scenario_id": sid,
                             "faults": [f.model_dump() for f in res.faults], "incidents": [i.model_dump() for i in res.incidents]})
        if self.recorder is not None:
            started = self._event_ids.get(sid)
            self.recorder.record("scenario", {"phase": "stopped", "scenario_id": sid,
                                              "faults": [f.model_dump() for f in res.faults],
                                              "incidents": [i.model_dump() for i in res.incidents]},
                                 caused_by=[started] if started else None)
            self.recorder.export()                           # a stopped scenario leaves its log file now
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
                incidents: list[Incident] | None = None, scenarios: list[ScenarioInfo] | None = None) -> ScenarioResult:
        tick = self.sim.tick
        return ScenarioResult(
            status=status, name=name, scenario_id=scenario_id, run_id=self.sim.run_id, tick=tick,
            time=self.sim.clock.iso_of(tick), scenarios=scenarios or [],
            incidents=[IncidentInfo(incident_id=i.incident_id, kind=i.kind, node_id=i.node_id, affected_nodes=list(i.weights),
                                    spread=i.spread,
                                    start_tick=i.start_tick, start_time=self.sim.clock.iso_of(i.start_tick), ramp_ticks=i.ramp_ticks,
                                    hold_ticks=i.hold_ticks, fade_ticks=i.fade_ticks, end_tick=i.end_tick) for i in (incidents or [])],
            faults=[FaultInfo(fault_id=f.fault_id, kind=f.kind, device_id=f.device_id, channel=f.channel,
                              start_tick=f.start_tick, start_time=self.sim.clock.iso_of(f.start_tick), end_tick=f.end_tick,
                              value=f.value, lag_ticks=f.lag_ticks) for f in (faults or [])])
