"""The city graph for CIVIS (agreed in the 23 Oct meeting): nodes, links, distances, zones, roads, and what each node can do.

Everything here is copied or computed from data the Twin already publishes in pieces (`list_nodes`, `list_actions`,
`topology.json`, `layout.json`). It adds nothing to the simulation and it is the same for the whole run (built once).

What is NOT in it, on purpose: normal ranges, noise, device quirks, true values. The Twin publishes no datasheet.

Distances are straight lines over the ground (haversine from the GPS positions, the formula the sensor table uses).
They are NOT distances along roads or pipes: the Twin has no pipe or road network to route on.
"""
import math

from pydantic import BaseModel

from .geo import bearing_deg, distance_m
from .models import Layout, Node, Topology

NEAR_ROAD_M = 25.0         # a node closer to a road than this counts as "on" it (traffic nodes are placed on roads)


class GraphAction(BaseModel):
    action: str
    risk: str | None
    preview_required: bool
    action_cap: int | None          # most nodes of one domain one request may touch


class GraphSensor(BaseModel):
    name: str
    unit: str
    device_id: str


class GraphNode(BaseModel):
    node_id: str
    label: str
    domains: list[str]
    shared: bool                    # True when the node belongs to more than one domain
    role: str
    zone: str
    x: float                        # map units, 1920 x 1080 canvas, y grows downwards
    y: float
    lat: float
    lon: float
    sensors: list[GraphSensor]
    actions: list[GraphAction]      # what `actuate` can do here (empty for sensor-only nodes)
    neighbours: list[str]           # this node's own nearest list (can be one-sided; the symmetric pairs are in `edges`)
    degree: int                     # how many links touch this node
    nearest_road_id: str
    nearest_road_kind: str
    distance_to_road_m: float
    on_road: bool


class GraphEdge(BaseModel):
    a: str
    b: str
    distance_m: float
    distance_map_units: float
    bearing_a_to_b_deg: float       # 0 = north, 90 = east
    kind: str                       # "same_domain" (they share a domain) or "cross_domain"
    shared_domains: list[str]
    same_zone: bool


class GraphZone(BaseModel):
    id: str
    name: str
    x: float
    y: float
    w: float
    h: float
    node_ids: list[str]


class GraphPoint(BaseModel):
    x: float
    y: float
    lat: float
    lon: float


class GraphRoad(BaseModel):
    id: str
    kind: str                       # "ring", "main" or "secondary"
    length_m: float
    points: list[GraphPoint]


class GraphGeo(BaseModel):
    anchor_lat: float
    anchor_lon: float
    metres_per_unit: float
    canvas_width: int
    canvas_height: int
    distance_method: str = "straight line over the ground (haversine from lat/lon). Not along roads or pipes."
    bearing: str = "degrees clockwise from north: 0 north, 90 east, 180 south, 270 west"


class CityGraph(BaseModel):
    schema_version: int = 1
    seed: int
    run_id: str
    node_count: int
    edge_count: int
    geo: GraphGeo
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    zones: list[GraphZone]
    roads: list[GraphRoad]
    node_order: list[str] | None = None            # row and column order of `distance_matrix_m`
    distance_matrix_m: list[list[float]] | None = None    # straight-line metres between every pair, 0.1 m steps


class NearNode(BaseModel):
    node_id: str
    domains: list[str]
    role: str
    zone: str
    distance_m: float
    bearing_deg: float              # direction from the node you asked about to this one
    linked: bool                    # True when the two are joined by a link in `edges`


class NearestNodes(BaseModel):
    from_node: str
    count: int
    nodes: list[NearNode]


def _seg_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Shortest distance from point P to the segment 1-2 (map units). Clamp the projection so it stays on the segment."""
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


class GraphBook:
    """Builds the graph once and answers questions about it."""

    def __init__(self, topology: Topology, layout: Layout | None, actions, run_id: str):
        self.topology, self.layout, self.run_id = topology, layout, run_id
        self.mpu = topology.geo.metres_per_unit
        self.by_id: dict[str, Node] = {n.node_id: n for n in topology.nodes}
        self.order = [n.node_id for n in topology.nodes]
        self.roles = {n.role for n in topology.nodes}
        self._actions: dict[str, list[GraphAction]] = {}
        for a in actions.actions:
            for node_id in a.target_nodes:
                self._actions.setdefault(node_id, []).append(
                    GraphAction(action=a.action, risk=a.risk, preview_required=a.preview_required, action_cap=a.action_cap))
        self._dist = {a: {b: distance_m(self.by_id[a].lat, self.by_id[a].lon, self.by_id[b].lat, self.by_id[b].lon)
                          for b in self.order} for a in self.order}
        self._edge_set = {tuple(sorted(e)) for e in topology.edges}
        self._full = self._build()

    # -- building -----------------------------------------------------------------------------------------------
    def _road_of(self, n: Node) -> tuple[str, str, float]:
        if not self.layout or not self.layout.roads:
            return "", "", -1.0
        best = (float("inf"), "", "")
        for road in self.layout.roads:
            for (x1, y1), (x2, y2) in zip(road.points, road.points[1:]):
                d = _seg_distance(n.x, n.y, x1, y1, x2, y2)
                if d < best[0]:
                    best = (d, road.id, road.kind)
        return best[1], best[2], round(best[0] * self.mpu, 1)

    def _latlon(self, x: float, y: float) -> tuple[float, float]:
        from .geo import to_latlon
        g = self.topology.geo
        return to_latlon(x, y, canvas_w=self.topology.canvas.width, canvas_h=self.topology.canvas.height,
                         anchor_lat=g.anchor_lat, anchor_lon=g.anchor_lon, metres_per_unit=g.metres_per_unit)

    def _build(self) -> CityGraph:
        t = self.topology
        degree: dict[str, int] = {i: 0 for i in self.order}
        edges: list[GraphEdge] = []
        for a, b in sorted(self._edge_set):
            na, nb = self.by_id[a], self.by_id[b]
            degree[a] += 1
            degree[b] += 1
            shared = sorted(set(na.domains) & set(nb.domains))
            edges.append(GraphEdge(
                a=a, b=b, distance_m=round(self._dist[a][b], 1),
                distance_map_units=round(math.hypot(na.x - nb.x, na.y - nb.y), 1),
                bearing_a_to_b_deg=round(bearing_deg(na.lat, na.lon, nb.lat, nb.lon), 1),
                kind="same_domain" if shared else "cross_domain", shared_domains=shared, same_zone=na.zone == nb.zone))
        nodes = []
        for n in t.nodes:
            road_id, road_kind, road_d = self._road_of(n)
            nodes.append(GraphNode(
                node_id=n.node_id, label=n.label, domains=n.domains, shared=len(n.domains) > 1, role=n.role, zone=n.zone,
                x=n.x, y=n.y, lat=n.lat, lon=n.lon,
                sensors=[GraphSensor(name=s.name, unit=s.unit, device_id=s.device_id) for s in n.sensors],
                actions=sorted(self._actions.get(n.node_id, []), key=lambda a: a.action), neighbours=n.neighbours,
                degree=degree[n.node_id], nearest_road_id=road_id, nearest_road_kind=road_kind,
                distance_to_road_m=road_d, on_road=0 <= road_d <= NEAR_ROAD_M))
        zones, roads = [], []
        if self.layout:
            for z in self.layout.zones:
                zones.append(GraphZone(id=z.id, name=z.name, x=z.x, y=z.y, w=z.w, h=z.h,
                                       node_ids=[n.node_id for n in t.nodes if n.zone == z.id]))
            for r in self.layout.roads:
                pts = [GraphPoint(x=x, y=y, lat=la, lon=lo) for (x, y) in r.points for (la, lo) in [self._latlon(x, y)]]
                length = sum(math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(r.points, r.points[1:])) * self.mpu
                roads.append(GraphRoad(id=r.id, kind=r.kind, length_m=round(length, 1), points=pts))
        return CityGraph(
            seed=t.seed, run_id=self.run_id, node_count=len(nodes), edge_count=len(edges),
            geo=GraphGeo(anchor_lat=t.geo.anchor_lat, anchor_lon=t.geo.anchor_lon, metres_per_unit=self.mpu,
                         canvas_width=t.canvas.width, canvas_height=t.canvas.height),
            nodes=nodes, edges=edges, zones=zones, roads=roads, node_order=self.order,
            distance_matrix_m=[[round(self._dist[a][b], 1) for b in self.order] for a in self.order])

    # -- answers ------------------------------------------------------------------------------------------------
    def graph(self, include_matrix: bool = True, include_roads: bool = True) -> CityGraph:
        g = self._full
        drop = {}
        if not include_matrix:
            drop.update(node_order=None, distance_matrix_m=None)
        if not include_roads:
            drop.update(roads=[])
        return g.model_copy(update=drop) if drop else g

    def nearest(self, node_id: str, domain: str | None, role: str | None, limit: int) -> NearestNodes:
        me = self.by_id[node_id]
        rows = []
        for other in self.order:
            n = self.by_id[other]
            if other == node_id or (domain and domain not in n.domains) or (role and n.role != role):
                continue
            rows.append(NearNode(node_id=other, domains=n.domains, role=n.role, zone=n.zone,
                                 distance_m=round(self._dist[node_id][other], 1),
                                 bearing_deg=round(bearing_deg(me.lat, me.lon, n.lat, n.lon), 1),
                                 linked=tuple(sorted((node_id, other))) in self._edge_set))
        rows.sort(key=lambda r: (r.distance_m, r.node_id))
        return NearestNodes(from_node=node_id, count=min(limit, len(rows)), nodes=rows[:limit])
