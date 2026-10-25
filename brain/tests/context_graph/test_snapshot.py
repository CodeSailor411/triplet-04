import pytest

from civis_brain.context_graph import ContextGraph, distance_m
from civis_brain.contracts import Node, Reading


def node(key, **kw):
    return Node(node_id=key, domains=["emergency"], role="asset", **kw)


def test_zero_coordinates_and_dateline_use_metres():
    assert distance_m(node("a", lat=0.0, lon=0.0), node("b", lat=0.0, lon=1.0)) == pytest.approx(111195, abs=1)
    assert distance_m(node("a", lat=0.0, lon=179.9), node("b", lat=0.0, lon=-179.9)) == pytest.approx(22239, abs=1)
    assert distance_m(node("a"), node("b", lat=0.0, lon=0.0)) is None


def test_graph_version_and_shared_assets_are_stable():
    a = node("a", neighbours=["b"], lat=0.0, lon=0.0)
    b = node("b", lat=0.0, lon=0.1)
    b.domains.append("traffic")
    graph = ContextGraph([a, b])
    assert graph.version == ContextGraph([b, a]).version
    assert len(graph.nodes) == 2
    with pytest.raises(ValueError):
        ContextGraph([a, a])
    b.lat = 0.2
    assert graph.version != ContextGraph([a, b]).version


def test_only_eligible_resources_are_ranked_and_missing_position_stays_unknown():
    graph = ContextGraph([node("place", lat=0.0, lon=0.0), node("near", lat=0.0, lon=0.01),
                          node("far", lat=0.0, lon=1.0), node("unknown")])
    ranked = graph.rank_eligible("place", ["far", "unknown"])
    assert [r["node_id"] for r in ranked] == ["far", "unknown"]
    assert ranked[-1]["distance_m"] is None


def test_graph_rejects_invalidated_or_other_run_evidence():
    graph = ContextGraph([node("a", neighbours=["b"]), node("b")])
    row = Reading(run_id="run", reading_id="r", tick=1, timestamp="2026-10-25T10:00:01Z",
                  node_id="a", device_id="d", sensor="emergency_calls", channel="medical",
                  value=2.0, unit="calls/min")
    args = dict(run_id="run", tick=1, evidence=[row], focus_ids=["a"])
    assert graph.explain(**args)["relationship"] == "geographic_only"
    for change in ({"invalid_ids": ["r"]}, {"blocked_devices": ["d"]}, {"run_id": "other"}, {"tick": 0}):
        with pytest.raises(ValueError):
            graph.explain(**{**args, **change})
