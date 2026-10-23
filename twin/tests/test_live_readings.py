"""Readings through the real Twin: the read tools and the live feed."""
import json

import httpx2
import pytest

from conftest import KEYS


def _events(text: str) -> list[tuple[str, dict]]:
    out, name = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            out.append((name, json.loads(line.split(":", 1)[1])))
    return out


@pytest.mark.parametrize("identity", ["city_brain", "guardian"])
async def test_get_readings_for_both_layers(mcp_client, identity):
    async with mcp_client(identity) as c:
        r = await c.call_tool("get_readings", {})
    data = r.structured_content
    assert not r.is_error and data["count"] == len(data["readings"]) > 60
    assert data["run_id"] == "run-42-001" and data["tick"] == 0 and data["time"] == "2026-10-05T08:00:00.000Z"


async def test_get_readings_filters(mcp_client):
    async with mcp_client("guardian") as c:
        water = (await c.call_tool("get_readings", {"domain": "water"})).structured_content
        one_node = (await c.call_tool("get_readings", {"node_id": "EMG-01"})).structured_content
        one_sensor = (await c.call_tool("get_readings", {"sensor": "pm25"})).structured_content
    assert {r["sensor"] for r in water["readings"]} == {"water_level", "flow_rate"}      # only water sensors, also at shared nodes
    assert {r["node_id"] for r in one_node["readings"]} == {"EMG-01"} and one_node["count"] == 4   # four call types
    assert {r["sensor"] for r in one_sensor["readings"]} == {"pm25"} and one_sensor["count"] == 8


async def test_get_readings_clear_errors(mcp_client):
    async with mcp_client("guardian") as c:
        bad_node = await c.call_tool("get_readings", {"node_id": "NOPE-99"})
        bad_sensor = await c.call_tool("get_readings", {"sensor": "radar"})
        bad_domain = await c.call_tool("get_readings", {"domain": "swimming_pool"})
    assert bad_node.is_error and "UNKNOWN_NODE" in bad_node.content[0].text
    assert bad_sensor.is_error and "UNKNOWN_SENSOR" in bad_sensor.content[0].text and "pm25" in bad_sensor.content[0].text
    assert bad_domain.is_error and "domain" in bad_domain.content[0].text.lower()


@pytest.mark.parametrize("tool", ["get_readings", "get_clock"])
async def test_read_tools_need_a_layer_key(mcp_client, tool):
    async with mcp_client(None) as c:
        no_key = await c.call_tool(tool, {})
    async with mcp_client("scenario") as c:
        scenario = await c.call_tool(tool, {})
    assert no_key.is_error and "UNAUTHENTICATED" in no_key.content[0].text
    assert scenario.is_error and "FORBIDDEN" in scenario.content[0].text


async def test_get_clock(mcp_client):
    async with mcp_client("city_brain") as c:
        data = (await c.call_tool("get_clock", {})).structured_content
    assert data == {"run_id": "run-42-001", "tick": 0, "time": "2026-10-05T08:00:00.000Z",
                    "tick_seconds": 1.0, "speed": 1.0, "running": False}


async def test_leak_test_through_the_live_twin(mcp_client, base_url):
    """Leak test, part 2: nothing the Twin hands out over MCP or the feed mentions truth, bias or noise."""
    async with mcp_client("guardian") as c:
        texts = [(await c.call_tool(t, a)).content[0].text for t, a in
                 [("get_readings", {}), ("get_clock", {}), ("list_nodes", {}), ("get_capabilities", {})]]
        tool_list = json.dumps([t.model_dump(mode="json") for t in (await c.list_tools()).tools])
    async with httpx2.AsyncClient() as h:
        feed = (await h.get(base_url + "/events?max_events=2", headers={"Authorization": f"Bearer {KEYS['guardian']}"})).text
    for text in (*texts, tool_list):
        for forbidden in ("true_value", "truth", "bias", "noise", "wobble", "ground_truth"):
            assert forbidden not in text.lower()
    assert "truth" not in feed.lower() and "bias" not in feed.lower()


async def test_feed_streams_one_readings_event_per_tick(running_url):
    async with httpx2.AsyncClient(timeout=10) as h:
        r = await h.get(running_url + "/events?max_events=5", headers={"Authorization": f"Bearer {KEYS['city_brain']}"})
    events = _events(r.text)
    assert events[0][0] == "hello" and events[0][1]["you_are"] == "city_brain"
    batches = [d for name, d in events if name == "readings"]
    assert len(batches) == 4
    ticks = [b["tick"] for b in batches]
    assert ticks == list(range(ticks[0], ticks[0] + 4))                   # no tick missing, in order
    assert all(b["count"] == len(b["readings"]) > 60 and b["run_id"] == "run-42-001" for b in batches)
    assert "id: run-42-001:" in r.text                                    # SSE ids for resuming later


async def test_feed_matches_the_read_tool(running_url, mcp_client):
    """The same tick gives identical readings whether you ask or listen."""
    async with httpx2.AsyncClient(timeout=10) as h:
        r = await h.get(running_url + "/events?max_events=2", headers={"Authorization": f"Bearer {KEYS['guardian']}"})
    batch = next(d for name, d in _events(r.text) if name == "readings")
    from twin.generator import generate
    from twin.settings import load_config
    from twin.sim import Simulation
    cfg = load_config()
    local = Simulation(generate(cfg)[0], cfg).readings_at(batch["tick"])
    assert json.loads(local.model_dump_json()) == {k: v for k, v in batch.items() if k != "skipped_ticks"}


async def test_simulation_reset_starts_a_new_run():
    from twin.generator import generate
    from twin.settings import load_config
    from twin.sim import Simulation
    cfg = load_config()
    sim = Simulation(generate(cfg)[0], cfg)
    await sim.advance(5)
    assert (sim.run_id, sim.tick) == ("run-42-001", 5)
    await sim.reset()
    assert (sim.run_id, sim.tick) == ("run-42-002", 0)
    assert await sim.wait_for_change(1, 5, timeout=0.1) is True          # a waiter sees the change
    assert await sim.wait_for_change(2, 0, timeout=0.05) is False        # and times out when nothing moves
