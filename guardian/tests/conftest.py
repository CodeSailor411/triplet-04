"""Use the explicitly local demo mode for legacy in-process API tests."""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn
from mcp.server import MCPServer
from mcp.types import CallToolResult

os.environ.setdefault("DEMO_MODE", "true")


@pytest.fixture
def start_real_twin_server():
    """Start a real MCP 2.3.0 streamable-HTTP peer for adapter tests."""
    @contextmanager
    def start(*, text_tools: set[str] | None = None, replies: dict[str, Any] | None = None):
        state = {
            "list_actions": {"actions": [{"action": "set_signal_plan"}]},
            "get_clock": {"simulated_time": 1_800_000_000.0},
            "list_nodes": {"nodes": []},
            "get_containment_state": {"quarantined": []},
        }
        state.update(replies or {})
        text_tools = text_tools or set()
        peer = MCPServer(name="real-twin-test-peer", version="2.3.0")

        def register_tool(name: str) -> None:
            if name in text_tools:
                def tool() -> str:
                    value = state[name]
                    if isinstance(value, BaseException):
                        raise value
                    return value if isinstance(value, str) else json.dumps(value)
                tool.__name__ = name
                peer.tool(name=name, structured_output=False)(tool)
            else:
                def tool() -> dict[str, Any]:
                    value = state[name]
                    if isinstance(value, BaseException):
                        raise value
                    if isinstance(value, CallToolResult):
                        return value
                    return value
                tool.__name__ = name
                peer.tool(name=name, structured_output=True)(tool)

        for tool_name in ("list_actions", "get_clock", "list_nodes", "get_containment_state"):
            register_tool(tool_name)

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        app = peer.streamable_http_app(
            streamable_http_path="/mcp", json_response=True,
            stateless_http=True, host="127.0.0.1",
        )
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="critical", access_log=False,
        ))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not server.started:
            server.should_exit = True
            thread.join(timeout=2)
            raise RuntimeError("real Twin MCP test server did not start")
        try:
            yield SimpleNamespace(base_url=f"http://127.0.0.1:{port}", state=state)
        finally:
            server.should_exit = True
            thread.join(timeout=3)

    return start
