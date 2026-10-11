"""Clock format, truth versus observed, determinism, and the leak checks."""
import json
import re
import statistics

import pytest

from twin.clock import SimClock
from twin.generator import generate
from twin.models import Reading
from twin.settings import load_config
from twin.sim import Simulation
from twin.util import now_iso

RFC3339_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


@pytest.fixture(scope="module")
def sim():
    cfg = load_config()
    topo, _ = generate(cfg)
    return Simulation(topo, cfg)


def test_clock_format_and_arithmetic():
    c = SimClock("2026-10-05T08:00:00.000Z", 1.0)
    assert c.iso_of(0) == "2026-10-05T08:00:00.000Z"
    assert c.iso_of(90) == "2026-10-05T08:01:30.000Z"
    assert SimClock("2026-10-05T08:00:00.000Z", 0.5).iso_of(3) == "2026-10-05T08:00:01.500Z"
    assert RFC3339_Z.match(now_iso())


def test_every_reading_has_the_agreed_fields(sim):
    batch = sim.readings_at(10)
    assert batch.count == len(batch.readings) > 60
    expected = {"run_id", "reading_id", "tick", "timestamp", "node_id", "device_id", "sensor", "channel", "value", "unit"}
    for r in batch.readings:
        assert set(r.model_dump()) == expected               # strict: nothing extra can leak out
        assert RFC3339_Z.match(r.timestamp) and r.tick == 10 and r.run_id == "run-42-001"
    assert len({r.reading_id for r in batch.readings}) == batch.count      # ids are unique within a tick


def test_channels_split_emergency_calls_and_free_units(sim):
    readings = sim.readings_at(0).readings
    calls = {r.channel for r in readings if r.sensor == "emergency_calls"}
    units = {r.channel for r in readings if r.sensor == "units_free"}
    assert calls == {"accident", "fire", "flood", "medical"} and units == {"police", "ambulance", "fire"}
    assert all(r.channel is None for r in readings if r.sensor not in ("emergency_calls", "units_free"))


def test_same_seed_same_readings_in_any_order(sim):
    cfg = load_config()
    topo, _ = generate(cfg)
    other = Simulation(topo, cfg)
    late_first = other.readings_at(500).model_dump_json()      # ask for a late tick first
    other.readings_at(3)
    assert sim.readings_at(500).model_dump_json() == late_first


def test_different_seed_different_readings():
    cfg = load_config()
    a, b = Simulation(generate(cfg, 42)[0], cfg), Simulation(generate(cfg, 7)[0], cfg)
    assert [r.value for r in a.readings_at(5).readings] != [r.value for r in b.readings_at(5).readings]


def test_observed_differs_from_truth_but_stays_close(sim):
    """Sensors are imperfect: observed is truth plus bias plus noise, and the truth is not what we publish."""
    diffs, same = [], 0
    for tick in range(0, 200, 5):
        for d in sim.devices:
            if sim.model.cfg.profiles[d.sensor].noise_sd == 0 and sim.model.cfg.profiles[d.sensor].bias_sd == 0:
                continue
            for ch in (d.channels or (None,)):
                t, o = sim.model.true_value(d, ch, tick), sim.model.observed_value(d, ch, tick)
                diffs.append(o - t)
                same += (o == round(t, sim.model.cfg.profiles[d.sensor].decimals))
    assert same / len(diffs) < 0.25                               # most observed values are not the truth
    assert abs(statistics.mean(diffs)) < 5 and statistics.pstdev(diffs) > 0


def test_values_wander_but_stay_in_a_normal_band(sim):
    water = [d for d in sim.devices if d.sensor == "water_level"]
    series = [sim.model.observed_value(water[0], None, t) for t in range(0, 1800)]
    assert max(series) - min(series) > 3                          # it moves
    assert 20 < min(series) and max(series) < 70                  # but a normal day never looks like a flood


def test_speed_moves_the_opposite_way_to_traffic_volume(sim):
    """avg_speed follows vehicle_count with a negative gain, so a rush of cars means slower traffic."""
    node = next(d.node_id for d in sim.devices if d.sensor == "vehicle_count")
    cnt = next(d for d in sim.devices if d.node_id == node and d.sensor == "vehicle_count")
    spd = next(d for d in sim.devices if d.node_id == node and d.sensor == "avg_speed")
    c = [sim.model.true_value(cnt, None, t) for t in range(0, 1200, 4)]
    s = [sim.model.true_value(spd, None, t) for t in range(0, 1200, 4)]
    assert statistics.correlation(c, s) < -0.3


def test_timestamps_wobble_but_stay_near_the_tick(sim):
    batch = sim.readings_at(60)
    stamps = {r.timestamp for r in batch.readings}
    assert len(stamps) > 1                                        # not all identical
    assert all("08:01:00" in t or "08:00:59" in t for t in stamps)


def test_a_null_value_is_valid_and_serialises_as_null():
    r = Reading(run_id="r", reading_id="x", tick=1, timestamp="2026-10-05T08:00:01.000Z", node_id="TRF-01",
                device_id="TRF-01.avg_speed", sensor="avg_speed", channel=None, value=None, unit="km/h")
    assert json.loads(r.model_dump_json())["value"] is None


def test_no_truth_anywhere_in_published_readings(sim):
    """Leak test, part 1: the serialised readings of 200 ticks never mention truth or carry the true value
    under another name. (Part 2, through the live Twin, is in test_live_readings.py.)"""
    text = "".join(sim.readings_at(t).model_dump_json() for t in range(200)).lower()
    for forbidden in ("true", "truth", "bias", "noise", "wobble", "profile", "ground"):
        assert forbidden not in text
    assert "value" in Reading.model_fields and not any("tru" in f for f in Reading.model_fields)
