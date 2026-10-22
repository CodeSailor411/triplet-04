"""Opt-in external Twin smoke test; skips explicitly when not configured."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from twin_adapter import TwinConnectionError, TwinSSEAdapter


@pytest.mark.skipif(not (os.environ.get("TWIN_BASE_URL") and os.environ.get("GUARDIAN_TWIN_BEARER_KEY")),
                    reason="live Twin not configured: set TWIN_BASE_URL and GUARDIAN_TWIN_BEARER_KEY")
def test_live_twin_sse_receives_hello_or_readings():
    async def receive_one():
        adapter = TwinSSEAdapter.from_env()
        async for event in adapter.events():
            if event["event"] in {"hello", "readings", "heartbeat"}:
                return event["event"]
        raise TwinConnectionError("Twin stream ended before a recognized event")

    event_name = asyncio.run(asyncio.wait_for(receive_one(), timeout=30))
    assert event_name in {"hello", "readings", "heartbeat"}


@pytest.mark.skipif(not (os.environ.get("TWIN_BASE_URL") and os.environ.get("GUARDIAN_TWIN_BEARER_KEY")),
                    reason="live Twin not configured: set TWIN_BASE_URL and GUARDIAN_TWIN_BEARER_KEY")
def test_live_twin_mcp_initializes_and_lists_tools():
    from twin_adapter import twin_config, twin_mcp_session

    async def list_tools():
        cfg = twin_config()
        async with twin_mcp_session(base_url=cfg["base_url"], bearer_key=cfg["bearer_key"],
                                    timeout=cfg["timeout"]) as session:
            return await session.list_tools()

    result = asyncio.run(asyncio.wait_for(list_tools(), timeout=30))
    assert result.tools is not None
