"""Containment: what Guardian can do to a sensor that looks wrong.

Four tools (all Guardian only, see auth.py):
  isolate_sensor     cut the device's data off the main feed.
  quarantine_device  same cut, plus: commands to that node are held in a side lane and not carried out.
  rollback_reading   replace one bad reading with the last trusted reported value (never the true value).
  release_device     undo isolate / quarantine / rollback for a device and give its cap slot back.

Caps count NODES per domain, like the action caps (see caps.py). Two pools:
  isolation pool  isolate + quarantine share it
  rollback pool   its own
A device counts in the domain of its own sensor (a pump station's power meter counts as Power, not as Water).
That is our pick for containment. It differs from `actuate`, where a shared node counts in every domain.
A request that would break a cap is refused as a whole (CAP_EXCEEDED), nothing is changed.

Nothing here reads a true value. Rollback only looks at what the sensor already REPORTED.
"""
import re
import threading
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel

from .actions import BadRequest
from .auth import Identity
from .caps import compute_caps
from .models import Topology
from .sensors import Device
from .settings import TwinConfig
from .sim import Simulation

MAX_IDS_PER_REQUEST = 100

_READING_ID = re.compile(r"^rd(\d{7})-(.+)$")


# ---------------------------------------------------------------------- shapes the tools hand out
class DeviceState(BaseModel):
    device_id: str
    node_id: str
    sensor: str
    domain: str
    state: Literal["isolated", "quarantined"]
    since_tick: int
    since_time: str
    reason: str | None = None


class ContainResult(BaseModel):
    status: Literal["applied", "rejected"]
    run_id: str
    tick: int
    time: str
    tool: str
    changed: list[str] = []          # devices whose state changed now
    unchanged: list[str] = []        # devices that were already in this state
    code: str | None = None          # only when rejected
    message: str | None = None
    details: dict[str, Any] | None = None


class CorrectedReading(BaseModel):
    """A bad reading replaced by the last trusted REPORTED value. Always marked corrected."""
    corrected: bool = True
    corrects: str                    # reading_id of the bad reading (CIVIS convention: keep the reference)
    restored_from: str               # reading_id of the trusted reading the value was taken from
    run_id: str
    tick: int                        # tick of the bad reading
    timestamp: str                   # simulated time of the bad reading
    node_id: str
    device_id: str
    sensor: str
    channel: str | None
    value: float
    unit: str


class RollbackResult(BaseModel):
    status: Literal["applied", "rejected"]
    run_id: str
    tick: int
    time: str
    corrections: list[CorrectedReading] = []
    already_corrected: list[str] = []    # reading_ids that had a correction before, returned unchanged
    code: str | None = None
    message: str | None = None
    details: dict[str, Any] | None = None


class ReleaseResult(BaseModel):
    run_id: str
    tick: int
    time: str
    released: list[str]
    not_contained: list[str]         # devices that had nothing to release


class PoolUse(BaseModel):
    domain: str
    isolation_cap: int
    isolation_in_use: int
    rollback_cap: int
    rollback_in_use: int


class ContainmentState(BaseModel):
    run_id: str
    tick: int
    time: str
    devices: list[DeviceState]
    corrections: list[CorrectedReading]
    pools: list[PoolUse]


class HeldCommand(BaseModel):
    tick: int
    time: str
    caller: str
    action: str
    targets: list[str]
    params: dict[str, Any]
    nodes: list[str]                 # the quarantined nodes that caused the hold


class LaneReading(BaseModel):
    reading_id: str
    device_id: str
    node_id: str
    sensor: str
    channel: str | None
    value: float | None
    unit: str


class QuarantineLane(BaseModel):
    run_id: str
    tick: int
    time: str
    held_readings: list[LaneReading]     # what quarantined devices report right now (kept out of the feed)
    held_commands: list[HeldCommand]


# ---------------------------------------------------------------------- the book
class ContainmentBook:
    def __init__(self, topology: Topology, config: TwinConfig, sim: Simulation):
        self.cfg, self.sim = config, sim
        self.nodes = {n.node_id: n for n in topology.nodes}
        self.devices: dict[str, Device] = {d.device_id: d for d in sim.devices}
        self.caps = compute_caps(config.generator, config.caps)
        self._lock = threading.RLock()
        self._run = sim.run_number
        self._reset_state()

    def _reset_state(self) -> None:
        self.contained: dict[str, DeviceState] = {}
        self.intervals: dict[str, list[list[int | None]]] = defaultdict(list)    # device -> [[from_tick, until_tick|None]]
        self.corrections: dict[tuple[str, str | None, int], CorrectedReading] = {}
        self.untrusted: dict[tuple[str, str | None], set[int]] = defaultdict(set)    # ticks known to be bad
        self.rolled_back: dict[str, int] = defaultdict(int)     # device -> number of active corrections
        self.held: list[HeldCommand] = []

    def _sync(self) -> None:
        if self._run != self.sim.run_number:          # a new run wipes everything, like in ActionBook
            self._run = self.sim.run_number
            self._reset_state()

    # ------------------------------------------------------------------ used by the simulation and actuate
    def is_hidden(self, device_id: str, tick: int) -> bool:
        with self._lock:
            self._sync()
            return self._hidden_at(device_id, tick)

    def _hidden_at(self, device_id: str, tick: int) -> bool:
        return any(a <= tick and (b is None or tick < b) for a, b in self.intervals.get(device_id, ()))

    def quarantined_nodes(self, targets: list[str]) -> list[str]:
        with self._lock:
            self._sync()
            bad = {s.node_id for s in self.contained.values() if s.state == "quarantined"}
            return sorted(t for t in targets if t in bad)

    def hold_command(self, caller: Identity, action: str, targets: list[str], params: dict[str, Any]) -> None:
        with self._lock:
            self._sync()
            tick = self.sim.tick
            self.held.append(HeldCommand(tick=tick, time=self.sim.clock.iso_of(tick), caller=caller.value,
                                         action=action, targets=list(targets), params=params,
                                         nodes=self.quarantined_nodes(targets)))
            del self.held[:-self.cfg.containment.held_commands_kept]

    # ------------------------------------------------------------------ isolate / quarantine
    def contain(self, tool: Literal["isolate_sensor", "quarantine_device"], device_ids: list[str],
                reason: str | None = None) -> ContainResult:
        state: Literal["isolated", "quarantined"] = "isolated" if tool == "isolate_sensor" else "quarantined"
        with self._lock:
            self._sync()
            devs = self._check_devices(device_ids)
            self._check_reason(reason)
            same = [d.device_id for d in devs if d.device_id in self.contained and self.contained[d.device_id].state == state]
            todo = [d for d in devs if d.device_id not in same]
            violations = self._violations("isolation", [d for d in todo if d.device_id not in self.contained])
            if violations:
                return self._contain_reject(tool, "CAP_EXCEEDED", violations)
            tick, now = self.sim.tick, self.sim.clock.iso_of(self.sim.tick)
            for d in todo:
                if d.device_id not in self.contained:                     # a switch isolated <-> quarantined keeps the old cut
                    self.intervals[d.device_id].append([tick, None])
                self.contained[d.device_id] = DeviceState(device_id=d.device_id, node_id=d.node_id, sensor=d.sensor,
                                                          domain=d.domain, state=state, since_tick=tick,
                                                          since_time=now, reason=reason)
            return ContainResult(status="applied", run_id=self.sim.run_id, tick=tick, time=now, tool=tool,
                                 changed=[d.device_id for d in todo], unchanged=same)

    # ------------------------------------------------------------------ release
    def release(self, device_ids: list[str]) -> ReleaseResult:
        with self._lock:
            self._sync()
            devs = self._check_devices(device_ids)
            tick = self.sim.tick
            released, nothing = [], []
            for d in devs:
                had = False
                if d.device_id in self.contained:
                    del self.contained[d.device_id]
                    for iv in self.intervals[d.device_id]:
                        if iv[1] is None:
                            iv[1] = tick                                  # data flows again from this tick
                    had = True
                if self.rolled_back.get(d.device_id):
                    for key in [k for k in self.corrections if k[0] == d.device_id]:
                        del self.corrections[key]
                    self.rolled_back[d.device_id] = 0                      # frees the rollback slot (and the correction records)
                    had = True
                (released if had else nothing).append(d.device_id)
            return ReleaseResult(run_id=self.sim.run_id, tick=tick, time=self.sim.clock.iso_of(tick),
                                 released=released, not_contained=nothing)

    # ------------------------------------------------------------------ rollback
    def rollback(self, reading_ids: list[str]) -> RollbackResult:
        with self._lock:
            self._sync()
            if not isinstance(reading_ids, list) or not 1 <= len(reading_ids) <= 50:
                raise BadRequest("INVALID_READING_IDS", "reading_ids must be a list of 1 to 50 reading ids.")
            if len(set(reading_ids)) != len(reading_ids):
                raise BadRequest("INVALID_READING_IDS", "reading_ids contains the same id twice.")
            parsed = [self._parse_reading_id(r) for r in reading_ids]          # (device, channel, tick)
            tick_now = self.sim.tick
            fresh, again = [], []
            for rid, (d, ch, t) in zip(reading_ids, parsed):
                if self._hidden_at(d.device_id, t):
                    raise BadRequest("READING_NOT_PUBLISHED", f"'{rid}' was never on the feed: the device was cut off at tick {t}.")
                (again if (d.device_id, ch, t) in self.corrections else fresh).append((rid, d, ch, t))
            violations = self._violations("rollback", [d for _, d, _, _ in fresh if not self.rolled_back.get(d.device_id)])
            if violations:
                return self._rollback_reject("CAP_EXCEEDED", "Too many nodes would be rolled back at once. "
                                             "The whole request was refused.", {**violations[0], "violations": violations})
            made = []
            for rid, d, ch, t in fresh:
                found = self._last_trusted(d, ch, t)
                if found is None:
                    return self._rollback_reject("NO_TRUSTED_VALUE", f"No trusted earlier value for '{rid}' within the last "
                                                 f"{self.cfg.containment.rollback_lookback_ticks} ticks. Nothing was changed.",
                                                 {"reading_id": rid})
                made.append((rid, d, ch, t, *found))
            for rid, d, ch, t, src_tick, value in made:                         # all checks passed: now change state
                self.untrusted[(d.device_id, ch)].add(t)
                self.rolled_back[d.device_id] += 1
                self.corrections[(d.device_id, ch, t)] = CorrectedReading(
                    corrects=rid, restored_from=_reading_id(src_tick, d, ch), run_id=self.sim.run_id, tick=t,
                    timestamp=self.sim.clock.iso_of(t), node_id=d.node_id, device_id=d.device_id, sensor=d.sensor,
                    channel=ch, value=value, unit=d.unit)
            return RollbackResult(status="applied", run_id=self.sim.run_id, tick=tick_now,
                                  time=self.sim.clock.iso_of(tick_now),
                                  corrections=[self.corrections[(d.device_id, ch, t)] for _, d, ch, t, *_ in made]
                                  + [self.corrections[(d.device_id, ch, t)] for _, d, ch, t in again],
                                  already_corrected=[rid for rid, *_ in again])

    def _last_trusted(self, d: Device, ch: str | None, tick: int) -> tuple[int, float] | None:
        """Walk back from tick-1: the first tick that was reported and not known to be bad. Observed values only."""
        bad = self.untrusted.get((d.device_id, ch), set())
        for t in range(tick - 1, max(-1, tick - 1 - self.cfg.containment.rollback_lookback_ticks), -1):
            if t in bad or self._hidden_at(d.device_id, t):
                continue
            if self.sim.faults is not None and self.sim.faults.is_faulty(d.device_id, ch, t):
                continue                                   # a faked, stuck or replayed tick is never "trusted"
            v = self.sim.model.observed_value(d, ch, t)
            if v is not None:
                return t, v
        return None

    # ------------------------------------------------------------------ read tools
    def state(self) -> ContainmentState:
        with self._lock:
            self._sync()
            tick = self.sim.tick
            iso_use, rb_use = self._pool_use("isolation"), self._pool_use("rollback")
            pools = [PoolUse(domain=dom, isolation_cap=c["isolation_cap"], isolation_in_use=iso_use.get(dom, 0),
                             rollback_cap=c["rollback_cap"], rollback_in_use=rb_use.get(dom, 0))
                     for dom, c in self.caps.items()]
            return ContainmentState(run_id=self.sim.run_id, tick=tick, time=self.sim.clock.iso_of(tick),
                                    devices=sorted(self.contained.values(), key=lambda s: s.device_id),
                                    corrections=sorted(self.corrections.values(), key=lambda c: (c.tick, c.device_id)),
                                    pools=pools)

    def lane(self) -> QuarantineLane:
        with self._lock:
            self._sync()
            tick = self.sim.tick
            readings = []
            for s in sorted(self.contained.values(), key=lambda s: s.device_id):
                if s.state != "quarantined":
                    continue
                d = self.devices[s.device_id]
                for ch in (d.channels or (None,)):
                    readings.append(LaneReading(reading_id=_reading_id(tick, d, ch), device_id=d.device_id,
                                                node_id=d.node_id, sensor=d.sensor, channel=ch,
                                                value=self.sim.reported(d, ch, tick).value, unit=d.unit))
            return QuarantineLane(run_id=self.sim.run_id, tick=tick, time=self.sim.clock.iso_of(tick),
                                  held_readings=readings, held_commands=list(self.held))

    # ------------------------------------------------------------------ pieces
    def _check_devices(self, device_ids: list[str]) -> list[Device]:
        if not isinstance(device_ids, list) or not 1 <= len(device_ids) <= MAX_IDS_PER_REQUEST:
            raise BadRequest("INVALID_DEVICE_IDS", f"device_ids must be a list of 1 to {MAX_IDS_PER_REQUEST} device ids.")
        if len(set(device_ids)) != len(device_ids):
            raise BadRequest("INVALID_DEVICE_IDS", "device_ids contains the same id twice.")
        for i in device_ids:
            if i not in self.devices:
                raise BadRequest("UNKNOWN_DEVICE", f"'{i}' is not a device. Device ids are in list_nodes (sensors[].device_id).")
        return [self.devices[i] for i in device_ids]

    @staticmethod
    def _check_reason(reason: str | None) -> None:
        if reason is not None and (not isinstance(reason, str) or len(reason) > 200):
            raise BadRequest("INVALID_REASON", "reason must be text of at most 200 characters.")

    def _parse_reading_id(self, rid: Any) -> tuple[Device, str | None, int]:
        m = _READING_ID.match(rid) if isinstance(rid, str) else None
        if not m:
            raise BadRequest("UNKNOWN_READING", f"'{rid}' is not a reading id. They look like rd0000123-WAT-03.water_level.")
        tick, rest = int(m.group(1)), m.group(2)
        for d in self.devices.values():
            for ch in (d.channels or (None,)):
                if rest == d.device_id + (f"-{ch}" if ch else ""):
                    if tick > self.sim.tick:
                        raise BadRequest("UNKNOWN_READING", f"'{rid}' is in the future (the clock is at tick {self.sim.tick}).")
                    return d, ch, tick
        raise BadRequest("UNKNOWN_READING", f"'{rid}' does not match any device of this city.")

    def _pool_nodes(self, pool: str) -> dict[str, set[str]]:
        """Domain -> nodes that currently use a slot in this pool."""
        nodes: dict[str, set[str]] = defaultdict(set)
        if pool == "isolation":
            for s in self.contained.values():
                nodes[s.domain].add(s.node_id)
        else:
            for dev_id, n in self.rolled_back.items():
                if n:
                    d = self.devices[dev_id]
                    nodes[d.domain].add(d.node_id)
        return nodes

    def _pool_use(self, pool: str) -> dict[str, int]:
        return {dom: len(v) for dom, v in self._pool_nodes(pool).items()}

    def _violations(self, pool: Literal["isolation", "rollback"], new: list[Device]) -> list[dict[str, Any]]:
        """Which caps would this request break? `new` = devices that are not in the pool yet."""
        used = self._pool_nodes(pool)
        added: dict[str, set[str]] = defaultdict(set)
        for d in new:
            if d.node_id not in used.get(d.domain, ()):                  # the node is already counted: no new slot
                added[d.domain].add(d.node_id)
        out = []
        for dom in self.caps:                                            # config order, so "first" is stable
            req, in_use, cap = len(added.get(dom, ())), len(used.get(dom, ())), self.caps[dom][f"{pool}_cap"]
            if req and in_use + req > cap:
                out.append({"pool": pool, "domain": dom, "cap": cap, "in_use": in_use, "requested": req,
                            "remaining": max(0, cap - in_use)})
        return out

    def _contain_reject(self, tool: str, code: str, violations: list[dict[str, Any]]) -> ContainResult:
        tick = self.sim.tick
        return ContainResult(status="rejected", run_id=self.sim.run_id, tick=tick, time=self.sim.clock.iso_of(tick),
                             tool=tool, code=code,
                             message="This request would put more nodes in the pool than the blast-radius cap allows. "
                                     "The whole request was refused, nothing was changed.",
                             details={**violations[0], "violations": violations})

    def _rollback_reject(self, code: str, message: str, details: dict[str, Any]) -> RollbackResult:
        tick = self.sim.tick
        return RollbackResult(status="rejected", run_id=self.sim.run_id, tick=tick, time=self.sim.clock.iso_of(tick),
                              code=code, message=message, details=details)


def _reading_id(tick: int, d: Device, ch: str | None) -> str:
    """Same format as sim.readings_at. Kept in one place here so the two cannot drift apart (a test checks it)."""
    return f"rd{tick:07d}-{d.device_id}" + (f"-{ch}" if ch else "")
