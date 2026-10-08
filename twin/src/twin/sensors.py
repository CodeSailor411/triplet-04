"""The sensor model: truth versus observed.

For every device and tick the Twin can work out two numbers:
  * the TRUE value  (what is really happening in the city). Never leaves the Twin.
  * the OBSERVED value (what the sensor reports): truth + this device's fixed bias + fresh noise.

Both are plain functions of (seed, device, tick). No state, no order dependence: asking for tick 500
before tick 3 gives the same numbers as the other way round, and the same seed replays the same city.
(Faults, actuator effects and scenarios will change the truth or the report later, on top of this.)
"""
import math
import random
from dataclasses import dataclass
from functools import lru_cache

from .models import Node
from .settings import ProfileCfg, SensorModelCfg


@dataclass(frozen=True)
class Device:
    """One physical sensor at one node. A node with two sensors has two devices."""
    device_id: str
    node_id: str
    sensor: str
    unit: str
    domain: str
    channels: tuple[str, ...]       # empty for normal sensors


@lru_cache(maxsize=200_000)
def _knot(seed: int, key: str, k: int) -> float:
    """A random target in [-1, 1] for wander segment k. Cached: neighbouring ticks reuse the same two."""
    return random.Random(f"{seed}:{key}:wander:{k}").uniform(-1.0, 1.0)


def _smooth_wander(seed: int, key: str, tick: int, every: int) -> float:
    """Smooth random movement: glide from one random target to the next (smoothstep, no sharp corners)."""
    k, frac = divmod(tick, every)
    f = frac / every
    s = f * f * (3 - 2 * f)
    a, b = _knot(seed, key, k), _knot(seed, key, k + 1)
    return a + (b - a) * s


class SensorModel:
    def __init__(self, seed: int, cfg: SensorModelCfg, devices: list[Device]):
        self.seed, self.cfg = seed, cfg
        self._by_node_sensor = {(d.node_id, d.sensor): d for d in devices}
        self._static: dict[tuple[str, str | None], tuple[float, float, float]] = {}
        for d in devices:
            self._check(d)

    def _check(self, d: Device) -> None:
        prof = self.cfg.profiles[d.sensor]
        if prof.follows and (d.node_id, prof.follows.sensor) not in self._by_node_sensor:
            raise ValueError(f"{d.device_id} follows '{prof.follows.sensor}' but that node has no such sensor")

    def _fixed(self, d: Device, channel: str | None) -> tuple[float, float, float]:
        """Per device (and channel), decided once: base level, wave phase, bias."""
        key = (d.device_id, channel)
        if key not in self._static:
            prof = self.cfg.profiles[d.sensor]
            rng = random.Random(f"{self.seed}:{d.device_id}:{channel}:fixed")
            base = prof.channels[channel] if channel else prof.base
            spread = self.cfg.device_spread if prof.spread is None else prof.spread
            base = base * (1 + spread * rng.uniform(-1, 1))
            phase = rng.uniform(0, 2 * math.pi)
            bias = rng.gauss(0, prof.bias_sd) if prof.bias_sd else 0.0
            self._static[key] = (base, phase, bias)
        return self._static[key]

    def _swing(self, d: Device, channel: str | None, tick: int) -> float:
        """How far the truth is away from its base right now (wave + wander), no following, no clamping."""
        prof = self.cfg.profiles[d.sensor]
        _, phase, _ = self._fixed(d, channel)
        wave = math.sin(2 * math.pi * tick / prof.wave_period_ticks + phase)
        wander = _smooth_wander(self.seed, f"{d.device_id}:{channel}", tick, prof.wander_ticks)
        return prof.wave_amp * wave + prof.wander_amp * wander

    @staticmethod
    def _clamp(prof: ProfileCfg, v: float) -> float:
        if prof.min_value is not None:
            v = max(prof.min_value, v)
        if prof.max_value is not None:
            v = min(prof.max_value, v)
        return v

    def true_value(self, d: Device, channel: str | None, tick: int) -> float:
        """PRIVATE. Only the Twin's own log and the tests may call this."""
        prof = self.cfg.profiles[d.sensor]
        base, _, _ = self._fixed(d, channel)
        v = base + self._swing(d, channel, tick)
        if prof.follows:
            leader = self._by_node_sensor[(d.node_id, prof.follows.sensor)]
            v += prof.follows.gain * self._swing(leader, None, tick)
        return self._clamp(prof, v)

    def observed_value(self, d: Device, channel: str | None, tick: int) -> float:
        prof = self.cfg.profiles[d.sensor]
        _, _, bias = self._fixed(d, channel)
        noise = random.Random(f"{self.seed}:{d.device_id}:{channel}:noise:{tick}").gauss(0, prof.noise_sd) \
            if prof.noise_sd else 0.0
        v = self._clamp(prof, self.true_value(d, channel, tick) + bias + noise)
        return round(v, prof.decimals)

    def timing_wobble_ms(self, d: Device, channel: str | None, tick: int) -> float:
        """A few ms early or late. Capped at 4 standard deviations so it can never run wild."""
        sd = self.cfg.timing_wobble_ms
        if not sd:
            return 0.0
        w = random.Random(f"{self.seed}:{d.device_id}:{channel}:wobble:{tick}").gauss(0, sd)
        return round(max(-4 * sd, min(4 * sd, w)), 1)


def devices_from_nodes(nodes: list[Node], sensor_domain: dict[str, str]) -> list[Device]:
    out: list[Device] = []
    for n in nodes:
        for s in n.sensors:
            out.append(Device(device_id=s.device_id, node_id=n.node_id, sensor=s.name, unit=s.unit,
                              domain=sensor_domain[s.name], channels=tuple(s.channels)))
    return out
