"""Twin MCP discovery and narrowly scoped outbound containment/read calls."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from guardian_config import TWIN_TOOLS
from twin_adapter import TwinConnectionError, twin_config, twin_mcp_session


class TwinDiscoveryError(RuntimeError):
    pass


class TwinToolRejected(TwinDiscoveryError):
    def __init__(self, tool: str, message: str):
        self.tool = tool
        self.message = message
        match = re.search(r"\b([A-Z][A-Z0-9_]{1,63}):", message)
        self.code = match.group(1) if match else None
        super().__init__(f"Twin tool rejected {tool}: {message}")


def _tool_error_message(response: Any) -> str:
    content = getattr(response, "content", None) or []
    for block in content:
        text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()[:240]
    return "Twin MCP tool returned an error"


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


async def call_twin_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Call one documented Twin tool with Guardian's separate bearer identity."""
    guardian_tools = {TWIN_TOOLS[key] for key in
                      ("isolate", "quarantine", "rollback", "release_device", "get_readings")}
    if name not in guardian_tools:
        raise TwinDiscoveryError(f"Twin tool is not in Guardian's configured contract: {name}")
    try:
        cfg = twin_config()
    except TwinConnectionError as exc:
        raise TwinDiscoveryError("Twin connection settings unavailable") from exc
    for attempt in range(cfg["max_retries"] + 1):
        try:
            async with twin_mcp_session(base_url=cfg["base_url"], bearer_key=cfg["bearer_key"],
                                        timeout=cfg["timeout"]) as session:
                response = await asyncio.wait_for(session.call_tool(name, arguments), timeout=cfg["timeout"])
                is_error, value = _tool_result_value(response)
                if is_error:
                    raise TwinToolRejected(name, _tool_error_message(response))
                return value
        except TwinDiscoveryError:
            raise
        except Exception as exc:
            if attempt >= cfg["max_retries"]:
                raise TwinDiscoveryError(f"Twin tool call failed: {name} ({type(exc).__name__})") from exc
            await asyncio.sleep(min(cfg["retry_base_seconds"] * (2 ** attempt), 8.0))


def call_twin_tool_sync(name: str, arguments: dict[str, Any]) -> Any:
    return asyncio.run(call_twin_tool(name, arguments))


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
