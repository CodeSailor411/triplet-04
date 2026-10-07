"""The three risky checks from 4 Oct, as permanent tests: MCP at "/", per-layer keys, hidden tool, SSE."""
import httpx2
import pytest

from conftest import KEYS


async def test_health_next_to_mcp(base_url):
    async with httpx2.AsyncClient() as h:
        r = await h.get(base_url + "/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["nodes"] == 38


async def test_capabilities_without_key_says_not_logged_in(mcp_client):
    async with mcp_client(None) as c:
        r = await c.call_tool("get_capabilities", {})
    data = r.structured_content
    assert data["authenticated_as"] is None
    assert data["protocol_version"] == "2026-07-28"
    assert data["mcp_sdk_version"] == "2.3.0"
    assert data["tools_you_can_call"] == ["get_capabilities"]        # no key: only the tool that works without one


async def test_capabilities_lists_only_tools_that_caller_can_really_call(mcp_client):
    """Row 25 fix: the list used to show actuate to everyone."""
    expected = {
        "city_brain": {"get_capabilities", "list_nodes", "get_readings", "get_clock", "list_actions", "actuate",
                       "get_containment_state"},
        "guardian": {"get_capabilities", "list_nodes", "get_readings", "get_clock", "list_actions",
                     "get_containment_state", "isolate_sensor", "quarantine_device", "rollback_reading",
                     "release_device", "get_quarantine_lane"},
        "scenario": {"get_capabilities", "run_scenario"},
    }
    for who, names in expected.items():
        async with mcp_client(who) as c:
            data = (await c.call_tool("get_capabilities", {})).structured_content
        assert set(data["tools_you_can_call"]) == names


@pytest.mark.parametrize("identity", ["city_brain", "guardian"])
async def test_layers_are_identified_by_their_own_key(mcp_client, identity):
    async with mcp_client(identity) as c:
        r = await c.call_tool("get_capabilities", {})
    assert r.structured_content["authenticated_as"] == identity


async def test_list_nodes_works_with_a_layer_key(mcp_client):
    async with mcp_client("city_brain") as c:
        everything = (await c.call_tool("list_nodes", {})).structured_content
        water = (await c.call_tool("list_nodes", {"domain": "water"})).structured_content
    assert everything["count"] == 38 and water["count"] == 9


@pytest.mark.parametrize("who", [None, "wrong"])
async def test_list_nodes_refuses_missing_or_wrong_key(mcp_client, who):
    async with mcp_client(None, key=who) as c:
        r = await c.call_tool("list_nodes", {})
    assert r.is_error and "UNAUTHENTICATED" in r.content[0].text


async def test_list_nodes_refuses_scenario_key(mcp_client):
    async with mcp_client("scenario") as c:
        r = await c.call_tool("list_nodes", {})
    assert r.is_error and "FORBIDDEN" in r.content[0].text


async def test_bad_input_gives_a_clear_error(mcp_client):
    async with mcp_client("guardian") as c:
        r = await c.call_tool("list_nodes", {"domain": "swimming_pool"})
    assert r.is_error and "domain" in r.content[0].text.lower()


async def test_scenario_tool_hidden_without_the_scenario_key(mcp_client):
    for identity in (None, "city_brain", "guardian"):
        async with mcp_client(identity) as c:
            names = [t.name for t in (await c.list_tools()).tools]
            assert "run_scenario" not in names
            r = await c.call_tool("run_scenario", {"name": "t5"})
            assert r.is_error and "Unknown tool" in r.content[0].text


async def test_scenario_tool_visible_and_reachable_with_the_scenario_key(mcp_client):
    async with mcp_client("scenario") as c:
        names = [t.name for t in (await c.list_tools()).tools]
        r = await c.call_tool("run_scenario", {"name": "t5"})
    assert "run_scenario" in names
    assert r.is_error and "NOT_IMPLEMENTED" in r.content[0].text      # reached the tool itself


async def test_hidden_tool_error_looks_like_a_missing_tool(mcp_client):
    async with mcp_client("city_brain") as c:
        hidden = await c.call_tool("run_scenario", {"name": "t5"})
        missing = await c.call_tool("no_such_tool", {"name": "t5"})
    assert hidden.is_error and missing.is_error
    same_shape = lambda r, n: (r.is_error, r.structured_content, [x.text.replace(n, "X") for x in r.content])
    assert same_shape(hidden, "run_scenario") == same_shape(missing, "no_such_tool")


async def test_published_topology_never_contains_ranges_or_truth(mcp_client):
    async with mcp_client("guardian") as c:
        r = await c.call_tool("list_nodes", {})
    text = r.content[0].text.lower()
    for forbidden in ("normal_range", "bias", "noise", "true_value", "truth"):
        assert forbidden not in text


async def test_sse_needs_a_layer_key(base_url):
    async with httpx2.AsyncClient() as h:
        no_key = await h.get(base_url + "/events?max_events=1")
        scenario = await h.get(base_url + "/events?max_events=1", headers={"Authorization": f"Bearer {KEYS['scenario']}"})
    assert no_key.status_code == 401 and no_key.json()["error"]["code"] == "UNAUTHENTICATED"
    assert scenario.status_code == 403


async def test_sse_streams_hello_then_heartbeats(base_url):
    async with httpx2.AsyncClient() as h:
        r = await h.get(base_url + "/events?max_events=3", headers={"Authorization": f"Bearer {KEYS['guardian']}"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.text.count("event: hello") == 1 and r.text.count("event: heartbeat") == 2
    assert '"you_are": "guardian"' in r.text
