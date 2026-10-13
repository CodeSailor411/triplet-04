"""GPS for every node and reading (12 Oct). Reference data only: nothing in the Twin checks distances."""
import math
import re

from twin.generator import generate
from twin.geo import distance_m, to_latlon
from twin.models import Reading

DECIMALS_OK = re.compile(r"^-?\d+(\.\d{1,5})?$")


def test_the_canvas_centre_is_the_anchor_point():
    assert to_latlon(960, 540, canvas_w=1920, canvas_h=1080, anchor_lat=36.0, anchor_lon=10.0, metres_per_unit=5.0) == (36.0, 10.0)


def test_north_is_up_and_east_is_right():
    kw = dict(canvas_w=1920, canvas_h=1080, anchor_lat=36.0, anchor_lon=10.0, metres_per_unit=5.0)
    lat_up, _ = to_latlon(960, 440, **kw)              # 100 units above the centre
    lat_down, _ = to_latlon(960, 640, **kw)
    _, lon_right = to_latlon(1060, 540, **kw)
    assert lat_up > 36.0 > lat_down and lon_right > 10.0


def test_gps_distance_matches_the_map_distance_times_the_scale(topology=None):
    """The whole point of the scale number: GPS distance between two nodes = map distance x metres_per_unit."""
    from twin.settings import load_config
    cfg = load_config()
    topo, _ = generate(cfg)
    scale = cfg.generator.geo.metres_per_unit
    worst = 0.0
    for n in topo.nodes:
        for m in topo.nodes:
            if n.node_id >= m.node_id:
                continue
            by_map = math.hypot(n.x - m.x, n.y - m.y) * scale
            by_gps = distance_m(n.lat, n.lon, m.lat, m.lon)
            worst = max(worst, abs(by_map - by_gps))
    assert worst < 3.0, f"GPS and map distances differ by up to {worst:.2f} m"        # 5 decimals = about 1.1 m steps


def test_every_node_has_its_own_fixed_position_and_shared_nodes_have_one(config):
    topo, _ = generate(config)
    spots = {(n.lat, n.lon) for n in topo.nodes}
    assert len(spots) == len(topo.nodes) == 38                         # no two nodes on the same spot
    assert any(len(n.domains) > 1 for n in topo.nodes)                 # shared nodes exist, and still have exactly one lat/lon
    for n in topo.nodes:
        assert 35.9 < n.lat < 36.1 and 9.9 < n.lon < 10.1              # the city stays near the anchor (about 10 km wide)
        assert DECIMALS_OK.match(repr(n.lat)) and DECIMALS_OK.match(repr(n.lon))     # at most 5 decimals


def test_same_seed_same_gps_and_the_topology_says_how_it_was_made(config):
    a, _ = generate(config)
    b, _ = generate(config)
    assert [(n.lat, n.lon) for n in a.nodes] == [(n.lat, n.lon) for n in b.nodes]
    assert (a.geo.anchor_lat, a.geo.anchor_lon, a.geo.metres_per_unit) == (36.0, 10.0, 5.0) and a.schema_version == 2


def test_readings_carry_the_gps_of_their_node(config):
    from twin.sim import Simulation
    topo, _ = generate(config)
    sim = Simulation(topo, config)
    by_id = {n.node_id: n for n in topo.nodes}
    batch = sim.readings_at(10)
    assert batch.count > 60
    for r in batch.readings:                                           # every single reading, not a sample
        assert (r.lat, r.lon) == (by_id[r.node_id].lat, by_id[r.node_id].lon)


def test_a_reading_without_gps_is_invalid():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Reading(run_id="r", reading_id="x", tick=1, timestamp="2026-10-05T08:00:01.000Z", node_id="TRF-01",
                device_id="TRF-01.avg_speed", sensor="avg_speed", channel=None, value=1.0, unit="km/h")
