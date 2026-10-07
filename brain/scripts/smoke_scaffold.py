"""Probe a running local scaffold. No AI/partner request is made."""

import asyncio

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from civis_brain.settings import Settings


async def probe(key: str | None, tool: str, arguments: dict):
    settings = Settings()
    url = f"http://127.0.0.1:{settings.brain_port}/mcp"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx2.AsyncClient(headers=headers) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            assert client.protocol_version == "2026-07-28"
            return await client.call_tool(tool, arguments)


async def main():
    settings = Settings()
    capability = await probe(None, "get_capabilities", {})
    assert capability.structured_content["ready"] is False
    missing = await probe(None, "get_active_incidents", {"run_id": "run-test"})
    assert missing.is_error and "UNAUTHENTICATED" in missing.content[0].text
    authenticated = await probe(settings.brain_twin_caller_key, "get_active_incidents",
                                {"run_id": "run-test"})
    assert authenticated.is_error and "NOT_IMPLEMENTED" in authenticated.content[0].text
    forbidden = await probe(settings.brain_twin_caller_key, "notify_containment", {"notice": {
        "event_id": "notice-1", "run_id": "run-test", "state": "isolated",
        "device_ids": ["WAT-01.water_level"], "reading_ids": [],
    }})
    assert forbidden.is_error and "FORBIDDEN" in forbidden.content[0].text
    print("PASS protocol 2026-07-28, discovery, auth, Guardian-only callback and honest NOT_IMPLEMENTED")


if __name__ == "__main__":
    asyncio.run(main())
