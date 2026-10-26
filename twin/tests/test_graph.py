"""The city graph for CIVIS (agreed 23 Oct): get_city_graph and get_nearest_nodes."""
import json
import math

import pytest

from twin.actions import ActionBook
from twin.generator import generate
from twin.geo import bearing_deg, distance_m
from twin.graph import GraphBook
from twin.settings import load_config
from twin.sim import Simulation


@pytest.fixture(scope="module")
def world():
    cfg = load_config()
    topo, layout = generate(cfg)
    sim = Simulation(topo, cfg)
    gb = GraphBook(topo, layout, ActionBook(topo, cfg, sim).list_actions(), sim.run_id)
    return cfg, topo, layout, gb


# ---------------------------------------------------------------- the math
def test_bearing_is_a_compass_direction():
    assert bearing_deg(36.0, 10.0, 36.1, 10.0) == pytest.approx(0, abs=0.01)         # due north
    assert bearing_deg(36.0, 10.0, 36.0, 10.1) == pytest.approx(90, abs=0.1)         # due east
    assert bearing_deg(36.0, 10.0, 35.9, 10.0) == pytest.approx(180, abs=0.01)       # due south
    assert bearing_deg(36.0, 10.0, 36.0, 9.9) == pytest.approx(270, abs=0.1)         # due west


# ---------------------------------------------------------------- the graph
def test_every_node_and_link_of_the_topology_is_in_the_graph(world):
    _, topo, _, gb = world
    g = gb.graph()
    assert g.node_count == len(g.nodes) == len(topo.nodes) == 38
    assert {n.node_id for n in g.nodes} == {n.node_id for n in topo.nodes}
    assert g.edge_count == len(g.edges) == len(topo.edges)
    assert {tuple(sorted((e.a, e.b))) for e in g.edges} == {tuple(sorted(e)) for e in topo.edges}


def test_distances_agree_with_gps_with_the_map_and_are_symmetric(world):
    _, topo, _, gb = world
    g = gb.graph()
    by = {n.node_id: n for n in topo.nodes}
    for e in g.edges:
        a, b = by[e.a], by[e.b]
        assert e.distance_m == pytest.approx(distance_m(a.lat, a.lon, b.lat, b.lon), abs=0.06)
        # the same distance measured on the map (x, y times metres per unit) must agree within GPS rounding (about 1 m)
        assert e.distance_m == pytest.approx(math.hypot(a.x - b.x, a.y - b.y) * g.geo.metres_per_unit, abs=3.0)
    m = g.distance_matrix_m
    n = len(g.node_order)
    assert len(m) == n and all(len(row) == n for row in m)
    assert all(m[i][i] == 0 for i in range(n))
    assert all(m[i][j] == m[j][i] for i in range(n) for j in range(n))


def test_matrix_row_order_is_node_order_and_matches_the_links(world):
    _, _, _, gb = world
    g = gb.graph()
    ix = {nid: i for i, nid in enumerate(g.node_order)}
    for e in g.edges:
        assert g.distance_matrix_m[ix[e.a]][ix[e.b]] == e.distance_m


def test_link_kind_and_shared_domains_are_right(world):
    _, topo, _, gb = world
    by = {n.node_id: n for n in topo.nodes}
    for e in gb.graph().edges:
        shared = sorted(set(by[e.a].domains) & set(by[e.b].domains))
        assert e.shared_domains == shared and e.kind == ("same_domain" if shared else "cross_domain")
        assert e.same_zone == (by[e.a].zone == by[e.b].zone)
    assert any(e.kind == "cross_domain" for e in gb.graph().edges)       # the call places are linked across domains


def test_degree_counts_the_links_that_touch_each_node(world):
    g = world[3].graph()
    for n in g.nodes:
        assert n.degree == sum(1 for e in g.edges if n.node_id in (e.a, e.b))


def test_nodes_know_what_they_can_do_and_its_risk(world):
    g = world[3].graph()
    wat = next(n for n in g.nodes if n.node_id == "WAT-01")
    assert [(a.action, a.risk, a.preview_required) for a in wat.actions] == [("set_valve_position", "R3", True)]
    assert all(n.actions == [] for n in g.nodes if n.node_id.startswith("AIR-"))       # air quality has no actuator
    assert next(n for n in g.nodes if n.node_id == "SH-03").shared is True


def test_traffic_nodes_are_on_a_road_and_the_roads_and_zones_are_there(world):
    _, topo, layout, gb = world
    g = gb.graph()
    traffic = [n for n in g.nodes if "traffic" in n.domains]
    assert traffic and all(n.on_road for n in traffic)
    assert {z.id for z in g.zones} == {z.id for z in layout.zones}
    assert {r.id for r in g.roads} == {r.id for r in layout.roads}
    assert all(r.length_m > 0 and len(r.points) >= 2 for r in g.roads)
    assert sorted(i for z in g.zones for i in z.node_ids) == sorted(n.node_id for n in g.nodes)   # every node is in one zone


def test_smaller_replies_drop_only_what_was_switched_off(world):
    gb = world[3]
    small = gb.graph(include_matrix=False, include_roads=False)
    assert small.distance_matrix_m is None and small.node_order is None and small.roads == []
    assert len(small.nodes) == 38 and len(small.edges) == 67 and len(small.zones) == 6
    assert gb.graph().distance_matrix_m is not None                    # and the full graph was not changed by that


def test_the_graph_is_the_same_every_time(world):
    cfg, _, _, gb = world
    topo, layout = generate(cfg)
    sim = Simulation(topo, cfg)
    again = GraphBook(topo, layout, ActionBook(topo, cfg, sim).list_actions(), sim.run_id).graph()
    assert again.model_dump_json() == gb.graph().model_dump_json()


def test_the_graph_leaks_nothing_private(world):
    """The Twin publishes no datasheet: no normal ranges, noise, device quirks or true values."""
    cfg, _, _, gb = world
    text = gb.graph().model_dump_json().lower()
    secret_words = {"noise", "bias", "wave", "wander", "drift", "true_value", "truth", "quirk", "min_value", "max_value",
                    "base_value", "decimals", "follows", "stuck", "seed_offset"}
    keys = set()

    def walk(x):
        if isinstance(x, dict):
            keys.update(x)
            [walk(v) for v in x.values()]
        elif isinstance(x, list):
            [walk(v) for v in x]
    walk(json.loads(text))
    assert not (keys & secret_words), keys & secret_words
    assert len(text) < 80_000                                          # one call stays a sensible size


# ---------------------------------------------------------------- nearest nodes
def test_nearest_is_sorted_filtered_and_limited(world):
    gb = world[3]
    r = gb.nearest("WAT-01", None, None, 5)
    d = [n.distance_m for n in r.nodes]
    assert r.from_node == "WAT-01" and r.count == 5 and d == sorted(d) and "WAT-01" not in {n.node_id for n in r.nodes}
    assert all("power" in n.domains for n in gb.nearest("WAT-01", "power", None, 50).nodes)
    assert all(n.role == "dispatch_center" for n in gb.nearest("EMG-01", None, "dispatch_center", 50).nodes)
    assert gb.nearest("WAT-01", None, None, 50).count == 37             # everyone else
    linked = {n.node_id for n in gb.nearest("WAT-01", None, None, 50).nodes if n.linked}
    assert linked == {e.b if e.a == "WAT-01" else e.a for e in gb.graph().edges if "WAT-01" in (e.a, e.b)}


# ---------------------------------------------------------------- over real MCP
async def test_both_calls_over_mcp_and_who_may_call_them(mcp_client):
    async with mcp_client("city_brain") as c:
        g = (await c.call_tool("get_city_graph", {})).structured_content
        small = (await c.call_tool("get_city_graph", {"include_matrix": False, "include_roads": False})).structured_content
        near = (await c.call_tool("get_nearest_nodes", {"node_id": "WAT-01", "domain": "power", "limit": 3})).structured_content
    assert g["node_count"] == 38 and g["edge_count"] == 67 and len(g["distance_matrix_m"]) == 38
    assert small["distance_matrix_m"] is None and small["roads"] == []
    assert [n["node_id"] for n in near["nodes"]][:2] == ["SH-03", "PWR-01"] and near["count"] == 3     # SH-03 is a shared water and power node
    async with mcp_client("guardian") as c:                                    # Guardian may read it too
        assert (await c.call_tool("get_city_graph", {})).structured_content["node_count"] == 38
    async with mcp_client("scenario") as c:                                    # the scenario key may not
        r = await c.call_tool("get_city_graph", {})
    assert r.is_error and "FORBIDDEN" in r.content[0].text
    async with mcp_client(None) as c:
        r = await c.call_tool("get_nearest_nodes", {"node_id": "WAT-01"})
    assert r.is_error and "UNAUTHENTICATED" in r.content[0].text


async def test_bad_requests_are_clear_refusals(mcp_client):
    async with mcp_client("city_brain") as c:
        for args, code in (({"node_id": "NOPE"}, "UNKNOWN_NODE"), ({"node_id": "WAT-01", "role": "king"}, "UNKNOWN_ROLE"),
                           ({"node_id": "WAT-01", "limit": 0}, "BAD_LIMIT"), ({"node_id": "WAT-01", "limit": 51}, "BAD_LIMIT")):
            r = await c.call_tool("get_nearest_nodes", args)
            assert r.is_error and code in r.content[0].text, (args, r.content[0].text)
