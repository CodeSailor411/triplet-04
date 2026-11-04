"""Tiny canned MCP peer fixtures; these do not emulate Twin behavior."""
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import twin_discovery


class CannedPeer:
    def __init__(self, names):
        self.names = names
        self.calls = []

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=n) for n in self.names])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(isError=False, structuredContent={
            "list_actions": {"actions": ["set_signal_plan"]},
            "get_clock": {"simulated_time": 42.0},
            "list_nodes": {"nodes": []},
            "get_containment_state": {"quarantined": []},
        }[name])


def _install_peer(monkeypatch, peer):
    monkeypatch.setattr(twin_discovery, "twin_config", lambda: {
        "base_url": "http://twin.invalid", "bearer_key": "test-only", "timeout": 3,
    })

    @asynccontextmanager
    async def session(**kwargs):
        yield peer

    monkeypatch.setattr(twin_discovery, "twin_mcp_session", session)


def test_discovery_lists_and_reads_required_twin_capabilities(monkeypatch):
    peer = CannedPeer(["list_actions", "get_clock", "list_nodes", "get_containment_state"])
    _install_peer(monkeypatch, peer)
    result = twin_discovery.discover_twin_sync()
    assert result["get_clock"] == {"simulated_time": 42.0}
    assert [name for name, _ in peer.calls] == [
        "list_actions", "get_clock", "list_nodes", "get_containment_state",
    ]


def test_discovery_fails_clearly_when_required_tool_is_missing(monkeypatch):
    peer = CannedPeer(["get_clock"])
    _install_peer(monkeypatch, peer)
    with pytest.raises(twin_discovery.TwinDiscoveryError, match="expected Twin discovery tool missing"):
        twin_discovery.discover_twin_sync()


def test_twin_mcp_session_opens_a_real_mcp_230_streamable_http_peer(start_real_twin_server):
    from twin_adapter import twin_mcp_session

    with start_real_twin_server() as peer:
        async def list_names():
            async with twin_mcp_session(base_url=peer.base_url, bearer_key="test-only") as session:
                return {tool.name for tool in (await session.list_tools()).tools}

        import asyncio
        names = asyncio.run(list_names())

    assert {"list_actions", "get_clock", "list_nodes", "get_containment_state"} <= names


def _install_real_peer(monkeypatch, peer):
    monkeypatch.setattr(twin_discovery, "twin_config", lambda: {
        "base_url": peer.base_url, "bearer_key": "test-only", "timeout": 3,
    })


def test_real_twin_discovery_reads_structured_content(start_real_twin_server, monkeypatch):
    with start_real_twin_server() as peer:
        _install_real_peer(monkeypatch, peer)
        result = twin_discovery.discover_twin_sync()

    assert result["get_clock"] == {"simulated_time": 1_800_000_000.0}
    assert result["list_actions"] == {"actions": [{"action": "set_signal_plan"}]}


def test_real_twin_discovery_falls_back_to_json_text_content(start_real_twin_server, monkeypatch):
    with start_real_twin_server(text_tools={"get_clock"}) as peer:
        _install_real_peer(monkeypatch, peer)
        result = twin_discovery.discover_twin_sync()

    assert result["get_clock"] == {"simulated_time": 1_800_000_000.0}


def test_real_twin_discovery_reports_sdk_error_replies(start_real_twin_server, monkeypatch):
    from mcp.types import CallToolResult, TextContent

    error = CallToolResult(isError=True, content=[TextContent(text="clock tool failed")])
    with start_real_twin_server(replies={"get_clock": error}) as peer:
        _install_real_peer(monkeypatch, peer)
        with pytest.raises(twin_discovery.TwinDiscoveryError, match="Twin discovery call failed: get_clock"):
            twin_discovery.discover_twin_sync()
