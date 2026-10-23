"""The city generator: counts, determinism, spacing, layout, caps."""
import math

import pytest

from twin.caps import compute_caps
from twin.generator import fingerprint, generate
from twin.settings import ConfigError, load_config


@pytest.fixture(scope="module")
def city():
    cfg = load_config()
    topo, layout = generate(cfg)
    return cfg, topo, layout


def test_node_counts(city):
    cfg, topo, _ = city
    assert len(topo.nodes) == 38
    memberships = sum(len(n.domains) for n in topo.nodes)
    assert memberships == 44
    assert sum(1 for n in topo.nodes if len(n.domains) > 1) == 6
    per_domain = {}
    for n in topo.nodes:
        for d in n.domains:
            per_domain[d] = per_domain.get(d, 0) + 1
    assert per_domain == {"traffic": 11, "water": 9, "power": 9, "air_quality": 8, "emergency": 7}


def test_shared_nodes_have_exactly_two_domains(city):
    _, topo, _ = city
    assert all(len(n.domains) in (1, 2) for n in topo.nodes)


def test_ids_unique(city):
    _, topo, _ = city
    ids = [n.node_id for n in topo.nodes]
    assert len(ids) == len(set(ids))


def test_emergency_nodes(city):
    _, topo, _ = city
    emergency = [n for n in topo.nodes if "emergency" in n.domains]
    assert sum(1 for n in emergency if n.role == "call_place") == 6
    dispatch = [n for n in emergency if n.role == "dispatch_center"]
    assert len(dispatch) == 1 and dispatch[0].actuators == ["dispatch"]
    assert all("emergency_calls" in [s.name for s in n.sensors] for n in emergency if n.role == "call_place")
    assert [s.name for s in dispatch[0].sensors] == ["units_free"]


def test_same_seed_same_city(city):
    cfg, topo, layout = city
    topo2, layout2 = generate(cfg)
    assert fingerprint(topo) == fingerprint(topo2)
    assert layout.model_dump_json() == layout2.model_dump_json()


def test_different_seed_different_city(city):
    cfg, topo, _ = city
    other, _ = generate(cfg, seed=cfg.seed + 1)
    assert fingerprint(other) != fingerprint(topo)
    assert len(other.nodes) == 38                    # still the same counts


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 2026])
def test_many_seeds_always_place_everything(city, seed):
    cfg, _, _ = city
    topo, _ = generate(cfg, seed=seed)
    assert len(topo.nodes) == 38


def test_spacing_and_bounds(city):
    cfg, topo, _ = city
    g = cfg.generator
    min_gap = g.node_size_px * g.min_spacing_factor
    for i, a in enumerate(topo.nodes):
        assert g.node_size_px <= a.x <= g.canvas.width - g.node_size_px
        assert g.node_size_px <= a.y <= g.canvas.height - g.node_size_px
        for b in topo.nodes[i + 1:]:
            assert math.hypot(a.x - b.x, a.y - b.y) >= min_gap - 0.01


def test_neighbours_exist_and_edges_match(city):
    _, topo, _ = city
    ids = {n.node_id for n in topo.nodes}
    for n in topo.nodes:
        assert n.node_id not in n.neighbours
        assert set(n.neighbours) <= ids and n.neighbours
    assert all(a < b and a in ids and b in ids for a, b in topo.edges)


def test_call_places_have_air_and_traffic_neighbours(city):
    _, topo, _ = city
    by_id = {n.node_id: n for n in topo.nodes}
    for n in topo.nodes:
        if n.role == "call_place":
            doms = {d for nb in n.neighbours for d in by_id[nb].domains}
            assert {"air_quality", "traffic"} <= doms


def test_layout_has_zones_and_roads_but_no_nodes(city):
    _, _, layout = city
    assert len(layout.zones) == 6 and len(layout.roads) >= 6
    assert "nodes" not in layout.model_dump()


def test_published_sensor_info_has_units_only(city):
    _, topo, _ = city
    dump = topo.model_dump_json()
    for forbidden in ("normal_range", "range", "bias", "noise", "true_value"):
        assert forbidden not in dump


def test_agreed_caps(city):
    cfg, _, _ = city
    caps = compute_caps(cfg.generator, cfg.caps)
    assert {d: c["action_cap"] for d, c in caps.items()} == {
        "traffic": 3, "water": 2, "power": 2, "air_quality": None, "emergency": 2}
    assert {d: c["isolation_cap"] for d, c in caps.items()} == {
        "traffic": 5, "water": 4, "power": 9, "air_quality": 4, "emergency": 3}
    assert all(c["rollback_cap"] == c["isolation_cap"] for c in caps.values())


def test_bad_config_gives_clear_error(city):
    cfg, _, _ = city
    bad = cfg.model_copy(deep=True)
    bad.generator.domains["traffic"].count = 1          # fewer nodes than shared nodes need
    with pytest.raises(ConfigError, match="traffic"):
        generate(bad)
