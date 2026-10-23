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
