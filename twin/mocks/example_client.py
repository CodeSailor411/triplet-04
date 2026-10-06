"""Smallest possible client: what City Brain or Guardian code does to talk to the Twin.
Shows a call with and without a key. The real mock Brain and mock Guardian arrive on 9 Oct.

    python mocks/example_client.py --url http://127.0.0.1:8000 --key dev-city-brain-key-change-me
"""
import argparse
import asyncio
import json

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def call(url: str, key: str | None, tool: str, args: dict):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx2.AsyncClient(headers=headers) as http:
        async with Client(streamable_http_client(url.rstrip("/") + "/mcp", http_client=http)) as client:
            return await client.call_tool(tool, args)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="where the Twin runs (set this in YOUR config)")
    ap.add_argument("--key", help="your key")
    ap.add_argument("--tool", default="get_capabilities")
    ap.add_argument("--args", default="{}", help='tool arguments as JSON, e.g. \'{"domain": "water"}\'')
    a = ap.parse_args()
    result = await call(a.url, a.key, a.tool, json.loads(a.args))
    print("is_error:", result.is_error)
    print(json.dumps(result.structured_content, indent=2) if result.structured_content else result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
