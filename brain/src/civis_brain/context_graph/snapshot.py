import hashlib
import json
import math

from civis_brain.contracts import Node, Reading


def distance_m(a: Node, b: Node) -> float | None:
    """Great-circle reference distance on WGS84 coordinates; no road-route claim."""
    if any(v is None for v in (a.lat, a.lon, b.lat, b.lon)):
        return None
    lat_a, lat_b = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat_b - lat_a, math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


class ContextGraph:
    """A versioned geographic snapshot, one vertex per unique real node ID.

    Discovery neighbours retain their geographic meaning. They never become
    pipes, roads or electrical dependencies. No permission or trust is derived.
    """

    def __init__(self, nodes: list[Node]):
        if len(nodes) > 2000 or len({n.node_id for n in nodes}) != len(nodes):
            raise ValueError("Graph discovery needs at most 2000 unique nodes")
        self.nodes = {n.node_id: n.model_copy(deep=True) for n in nodes}
        canonical = [self.nodes[key].model_dump(mode="json") for key in sorted(self.nodes)]
        for row in canonical:
            for field in ("domains", "actuators", "neighbours"):
                row[field] = sorted(set(row[field]))
        self.version = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:24]

    def rank_eligible(self, destination: str, eligible_ids: list[str]) -> list[dict]:
        """Caller supplies eligible resources. Missing coordinates rank last, by ID."""
        location = self.nodes[destination]
        rows = [
            {"node_id": key, "distance_m": distance_m(location, self.nodes[key]),
             "basis": "great_circle_reference"}
            for key in sorted(set(eligible_ids)) if key in self.nodes
        ]
        return sorted(rows, key=lambda r: (
            r["distance_m"] is None, r["distance_m"] if r["distance_m"] is not None else 0,
            r["node_id"],
        ))

    def explain(self, *, run_id: str, tick: int, evidence: list[Reading],
                focus_ids: list[str], invalid_ids=(), blocked_devices=()) -> dict:
        if any(r.run_id != run_id or r.tick > tick for r in evidence):
            raise ValueError("Graph evidence must belong to this run and not the future")
        if any(r.reading_id in invalid_ids or r.device_id in blocked_devices or r.value is None
               for r in evidence):
            raise ValueError("Graph context requires current eligible evidence")
        supported = {r.node_id for r in evidence}
        all_focus = set(focus_ids) & supported & self.nodes.keys()
        focus = sorted(all_focus)[:32]
        return {
            "graph_version": self.version, "run_id": run_id, "tick": tick,
            "evidence": [{"reading_id": r.reading_id, "node_id": r.node_id, "tick": r.tick}
                         for r in evidence],
            "focus_nodes": sorted(focus),
            "nearby": {key: self.rank_eligible(key, sorted(self.nodes[key].neighbours)[:64])[:10]
                       for key in sorted(focus)},
            "relationship": "geographic_only",
            "unique_assets": len(self.nodes),
            "context_truncated": len(all_focus) > len(focus),
        }
