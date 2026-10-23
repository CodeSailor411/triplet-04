"""Thin, read-only Twin MCP discovery client.

This module transports calls only. It does not implement Twin behavior. The
placeholder names and schemas are marked CONFIRM until partners approve them.
"""
from __future__ import annotations

import asyncio
from typing import Any

from guardian_config import TWIN_TOOLS
from twin_adapter import TwinConnectionError, twin_config, twin_mcp_session


class TwinDiscoveryError(RuntimeError):
    pass


async def discover_twin(*, timeout_seconds: float | None = None) -> dict[str, Any]:
    try:
        cfg = twin_config()
    except TwinConnectionError as exc:
        raise TwinDiscoveryError("Twin connection settings unavailable") from exc
    timeout = timeout_seconds or min(cfg["timeout"], 3.0)
    try:
        async with twin_mcp_session(base_url=cfg["base_url"], bearer_key=cfg["bearer_key"],
                                    timeout=timeout) as session:
            listed = await asyncio.wait_for(session.list_tools(), timeout=timeout)
            names = {tool.name for tool in listed.tools}
            required = [TWIN_TOOLS[k] for k in ("list_actions", "get_clock", "list_nodes",
                                                  "get_containment_state")]
            missing = [name for name in required if name not in names]
            if missing:
                raise TwinDiscoveryError("expected Twin discovery tool missing: " + ", ".join(missing))
            result: dict[str, Any] = {"tool_names": sorted(names)}
            for key in ("list_actions", "get_clock", "list_nodes", "get_containment_state"):
                response = await asyncio.wait_for(session.call_tool(TWIN_TOOLS[key], {}), timeout=timeout)
                if response.isError:
                    raise TwinDiscoveryError(f"Twin discovery call failed: {key}")
                result[key] = response.structuredContent or response.model_dump(mode="json")
            actions = result["list_actions"]
            if isinstance(actions, dict):
                actions = actions.get("actions", actions.get("result"))
            if isinstance(actions, list):
                caps = {}
                for item in actions:
                    if isinstance(item, dict) and isinstance(item.get("capacity"), dict):
                        domain = item.get("domain")
                        if isinstance(domain, str):
                            caps[domain] = item["capacity"]
                if caps:
                    result["discovered_capacities"] = caps
            return result
    except TwinDiscoveryError:
        raise
    except Exception as exc:
        raise TwinDiscoveryError(f"Twin discovery failed: {type(exc).__name__}") from exc


def discover_twin_sync(*, timeout_seconds: float | None = None) -> dict[str, Any]:
    return asyncio.run(discover_twin(timeout_seconds=timeout_seconds))
