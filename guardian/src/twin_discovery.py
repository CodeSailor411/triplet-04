"""Thin, read-only Twin MCP discovery client.

This module transports calls only. It does not implement Twin behavior. The
placeholder names and schemas are marked CONFIRM until partners approve them.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from guardian_config import TWIN_TOOLS
from twin_adapter import TwinConnectionError, twin_config, twin_mcp_session


class TwinDiscoveryError(RuntimeError):
    pass


def _tool_result_value(response: Any) -> tuple[bool, Any]:
    """Read the SDK 2.x result fields while tolerating older peer fixtures."""
    is_error = getattr(response, "is_error", None)
    if is_error is None:
        is_error = getattr(response, "isError", False)
    if is_error:
        return True, None

    structured = getattr(response, "structured_content", None)
    if structured is None:
        structured = getattr(response, "structuredContent", None)
    if structured is not None:
        return False, structured

    content = getattr(response, "content", None) or []
    text_parts = []
    for block in content:
        if isinstance(block, dict):
            text = block.get("text") if block.get("type") == "text" else None
        else:
            text = getattr(block, "text", None) if getattr(block, "type", None) == "text" else None
        if isinstance(text, str):
            text_parts.append(text)
    if text_parts:
        joined = "\n".join(text_parts)
        try:
            return False, json.loads(joined)
        except json.JSONDecodeError:
            return False, joined

    model_dump = getattr(response, "model_dump", None)
    return False, model_dump(mode="json") if callable(model_dump) else response


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
            failed_tool = None
            for key in ("list_actions", "get_clock", "list_nodes", "get_containment_state"):
                response = await asyncio.wait_for(session.call_tool(TWIN_TOOLS[key], {}), timeout=timeout)
                is_error, value = _tool_result_value(response)
                if is_error:
                    failed_tool = key
                    break
                result[key] = value
            if failed_tool is None:
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
        if failed_tool is not None:
            raise TwinDiscoveryError(f"Twin discovery call failed: {failed_tool}")
    except TwinDiscoveryError:
        raise
    except Exception as exc:
        raise TwinDiscoveryError(f"Twin discovery failed: {type(exc).__name__}") from exc


def discover_twin_sync(*, timeout_seconds: float | None = None) -> dict[str, Any]:
    return asyncio.run(discover_twin(timeout_seconds=timeout_seconds))


async def read_twin_clock(*, timeout_seconds: float | None = None) -> Any:
    """Read the configured Twin clock directly for each token issue/verify."""
    try:
        cfg = twin_config()
    except TwinConnectionError as exc:
        raise TwinDiscoveryError("Twin clock connection settings unavailable") from exc
    timeout = timeout_seconds or min(cfg["timeout"], 3.0)
    failed = False
    try:
        async with twin_mcp_session(base_url=cfg["base_url"], bearer_key=cfg["bearer_key"],
                                    timeout=timeout) as session:
            response = await asyncio.wait_for(session.call_tool(TWIN_TOOLS["get_clock"], {}), timeout=timeout)
            is_error, value = _tool_result_value(response)
            if not is_error:
                return value
            failed = True
    except TwinDiscoveryError:
        raise
    except Exception as exc:
        raise TwinDiscoveryError(f"Twin clock read failed: {type(exc).__name__}") from exc
    if failed:
        raise TwinDiscoveryError("Twin clock tool returned an error")


def read_twin_clock_sync(*, timeout_seconds: float | None = None) -> Any:
    return asyncio.run(read_twin_clock(timeout_seconds=timeout_seconds))
