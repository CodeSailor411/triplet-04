import asyncio
import json
import re

import httpx2
from jsonschema import ValidationError, validate
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from civis_brain.errors import BrainError

PROTOCOL_VERSION = "2026-07-28"


class MCPPeer:
    """Authenticated, bounded transport. New session per call avoids leaked lifetimes."""

    is_fixture = False

    def __init__(self, url: str, key: str, timeout_seconds: float = 5):
        self.url = url
        self.key = key
        self.timeout_seconds = timeout_seconds

    async def call_tool(self, name: str, arguments: dict) -> dict:
        async def request():
            async with httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {self.key}"},
                timeout=self.timeout_seconds,
            ) as http:
                async with Client(
                    streamable_http_client(self.url, http_client=http),
                    read_timeout_seconds=self.timeout_seconds,
                ) as client:
                    if client.protocol_version != PROTOCOL_VERSION:
                        raise BrainError(
                            "PROTOCOL_MISMATCH", "Peer negotiated a different MCP version"
                        )
                    tools = []
                    cursor = None
                    for _ in range(10):
                        listing = await client.list_tools(cursor=cursor, cache_mode="refresh")
                        tools.extend(listing.tools)
                        cursor = listing.next_cursor
                        if cursor is None:
                            break
                    if cursor is not None:
                        raise BrainError("PEER_SCHEMA_INVALID", "Peer tool listing is too large")
                    tool = next((tool for tool in tools if tool.name == name), None)
                    if tool is None:
                        raise BrainError(
                            "TOOL_UNAVAILABLE", "Configured peer tool is not advertised"
                        )
                    try:
                        validate(arguments, tool.input_schema)
                    except ValidationError:
                        raise BrainError(
                            "PEER_SCHEMA_INVALID", "Request disagrees with advertised schema"
                        ) from None
                    result = await client.call_tool(name, arguments)
                    if result.is_error:
                        # Keep safe refusal codes; raw text can include keys or injected instructions.
                        message = next(
                            (part.text for part in result.content if hasattr(part, "text")), ""
                        )
                        match = re.search(r"(?:^|:\s)([A-Z][A-Z0-9_]{1,63}):", message)
                        code = match.group(1) if match else "PEER_ERROR"
                        raise BrainError(code, "Peer refused the configured request")
                    value = result.structured_content
                    if value is None:
                        text = next(
                            (part.text for part in result.content if hasattr(part, "text")), ""
                        )
                        value = json.loads(text)
                    if not isinstance(value, dict):
                        raise BrainError(
                            "PEER_SCHEMA_INVALID", "Peer tool must return a structured object"
                        )
                    return value

        try:
            return await asyncio.wait_for(request(), self.timeout_seconds)
        except BrainError:
            raise
        except TimeoutError:
            raise BrainError("PEER_TIMEOUT", "Peer call timed out") from None
        except ExceptionGroup as group:

            def leaves(error):
                if isinstance(error, BaseExceptionGroup):
                    return [leaf for child in error.exceptions for leaf in leaves(child)]
                return [error]

            errors = leaves(group)
            refusal = next((error for error in errors if isinstance(error, BrainError)), None)
            if refusal is not None:
                raise refusal from None
            if any(isinstance(error, TimeoutError) for error in errors):
                raise BrainError("PEER_TIMEOUT", "Peer call timed out") from None
            raise BrainError(
                "PEER_UNAVAILABLE", "Peer transport or response is unavailable"
            ) from None
        except Exception:
            raise BrainError(
                "PEER_UNAVAILABLE", "Peer transport or response is unavailable"
            ) from None


def at_path(value: dict, path: str):
    for name in path.split("."):
        if not isinstance(value, dict) or name not in value:
            raise BrainError(
                "GUARDIAN_SCHEMA_INVALID", "Configured Guardian response field is missing"
            )
        value = value[name]
    return value


class MappedGuardianPeer:
    """Explicit mapping of a confirmed partner contract to CIVIS internal fields."""

    is_fixture = False

    def __init__(self, peer: MCPPeer, mapping: dict, score_tool: str, token_tool: str):
        self.peer = peer
        self.mapping = mapping
        self.score_tool = score_tool
        self.token_tool = token_tool

    async def call_tool(self, name: str, arguments: dict) -> dict:
        role = (
            "capabilities"
            if name == "get_capabilities"
            else "score"
            if name == self.score_tool
            else "approval"
            if name == self.token_tool
            else None
        )
        if role is None:
            raise BrainError("TOOL_UNAVAILABLE", "Guardian tool has no confirmed mapping")
        spec = self.mapping.get(role)
        if not isinstance(spec, dict):
            raise BrainError(
                "GUARDIAN_SCHEMA_UNCONFIRMED", "Guardian adapter mapping is incomplete"
            )
        request_fields = spec.get("request_fields", {})
        if set(request_fields) != set(arguments):
            raise BrainError(
                "GUARDIAN_SCHEMA_INVALID", "Request fields differ from the confirmed mapping"
            )
        wire = {request_fields[key]: value for key, value in arguments.items()}
        reply = await self.peer.call_tool(spec.get("tool", name), wire)
        return {key: at_path(reply, path) for key, path in spec["response_fields"].items()}
