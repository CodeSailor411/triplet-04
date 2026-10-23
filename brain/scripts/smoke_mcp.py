"""Exercise the real HTTP/MCP transport locally; no external peer or AI call."""

import asyncio
import json
import logging
import socket
import threading
import time
from pathlib import Path

import uvicorn

from civis_brain.app import create_app
from civis_brain.errors import BrainError
from civis_brain.integration.mcp_peer import MCPPeer
from civis_brain.settings import Settings


async def probe(url, settings):
    caller = MCPPeer(url, settings.brain_scenario_key, 5)
    capability = await caller.call_tool("get_capabilities", {})
    assert capability["protocol_version"] == "2026-07-28" and capability["ready"] is False
    case = json.loads((Path(settings.brain_config_root) / settings.brain_fixture_case).read_text())
    for batch in case["batches"]:
        result = await caller.call_tool("evaluate_tick", {"batch": batch})
    assert result["decisions"][0]["status"] == "alert"
    incidents = await caller.call_tool(
        "get_active_incidents", {"run_id": case["batches"][0]["run_id"]}
    )
    assert incidents["incidents"][0]["kind"] == "air_pollution"
    decision = await caller.call_tool(
        "explain_decision",
        {
            "decision_id": result["decisions"][0]["decision_id"],
        },
    )
    assert decision["found"]
    notice = {
        "event_id": "smoke-1",
        "run_id": case["batches"][0]["run_id"],
        "state": "quarantined",
        "device_ids": ["AQ-01.pm25"],
        "reading_ids": [],
    }
    for peer, name, arguments, code in [
        (caller, "notify_containment", {"notice": notice}, "FORBIDDEN"),
        (
            MCPPeer(url, "invalid-fixture-key", 5),
            "get_active_incidents",
            {"run_id": "elyes-demo"},
            "UNAUTHENTICATED",
        ),
        (caller, "not_advertised", {}, "TOOL_UNAVAILABLE"),
    ]:
        try:
            await peer.call_tool(name, arguments)
            raise AssertionError("Unauthorized or unavailable call succeeded")
        except BrainError as error:
            assert error.code == code, (error.code, code)
    guardian = MCPPeer(url, settings.brain_guardian_caller_key, 5)
    response = await guardian.call_tool("notify_containment", {"notice": notice})
    assert response["accepted"]
    assert not (await caller.call_tool("get_active_incidents", {"run_id": notice["run_id"]}))[
        "incidents"
    ]
    print(
        "PASS: MCP negotiation, discovery, evaluate, incident/explanation, caller restrictions, containment"
    )


def main():
    settings = Settings(_env_file=None, peer_mode="fixture", llm_mode="fixture")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    for name in ("httpx", "httpx2", "mcp"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            raise SystemExit("Local MCP smoke server did not start")
        asyncio.run(probe(f"http://127.0.0.1:{port}/mcp", settings))
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        sock.close()


if __name__ == "__main__":
    main()
