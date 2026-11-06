import asyncio
import json
import re
import time

import httpx2
from jsonschema import ValidationError, validate
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from civis_brain.errors import BrainError
from civis_brain.integration.journal import EVENT_CONTEXT

PROTOCOL_VERSION = "2026-07-28"


class MCPPeer:
    """Authenticated, bounded transport. New session per call avoids leaked lifetimes."""

    is_fixture = False

    def __init__(self, url: str, key: str, timeout_seconds: float = 5):
        self.url = url
        self.key = key
        self.timeout_seconds = timeout_seconds
        self.journal = None
        self.peer_name = "peer"

    async def list_tool_names(self) -> list[str]:
        """Read-only partner inventory for the handover connection check."""
        started = time.monotonic()
        context = dict(EVENT_CONTEXT.get())
        if self.journal is not None:
            self.journal.append({**context, "event": "mcp_inventory_request_sent",
                                 "peer": self.peer_name})
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx2.AsyncClient(
                    headers={"Authorization": f"Bearer {self.key}"},
                    timeout=self.timeout_seconds,
                ) as http:
                    async with Client(
                        streamable_http_client(self.url, http_client=http),
                        read_timeout_seconds=self.timeout_seconds,
                    ) as client:
                        if client.protocol_version != PROTOCOL_VERSION:
                            raise BrainError("PROTOCOL_MISMATCH", "Unexpected MCP protocol")
                        names, cursor = [], None
                        for _ in range(10):
                            page = await client.list_tools(cursor=cursor, cache_mode="refresh")
                            names.extend(tool.name for tool in page.tools)
                            cursor = page.next_cursor
                            if cursor is None:
                                if self.journal is not None:
                                    self.journal.append({
                                        **context, "event": "mcp_inventory_response_received",
                                        "peer": self.peer_name, "outcome": "success",
                                        "tool_names": names,
                                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                                    })
                                return names
                        raise BrainError("PEER_SCHEMA_INVALID", "Peer inventory exceeds page limit")
        except BrainError as error:
            if self.journal is not None:
                self.journal.append({
                    **context, "event": "mcp_inventory_response_received",
                    "peer": self.peer_name, "outcome": "failure", "code": error.code,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                })
            raise
        except Exception:
            if self.journal is not None:
                self.journal.append({
                    **context, "event": "mcp_inventory_response_received",
                    "peer": self.peer_name, "outcome": "failure", "code": "PEER_UNAVAILABLE",
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                })
            raise BrainError("PEER_UNAVAILABLE", "Check peer URL, Bearer key and protocol") from None

    async def call_tool(self, name: str, arguments: dict) -> dict:
        started = time.monotonic()
        event_context = dict(EVENT_CONTEXT.get())
        refs = self._event_refs(arguments)
        if self.journal is not None:
            self.journal.append({
                **event_context, "event": "mcp_tool_request_sent", "peer": self.peer_name, "tool": name,
                **refs, "request_summary": self._event_summary(arguments),
            })
            if (self.journal.write_error and
                    ((self.peer_name == "twin" and name in {"actuate", "commit_action"})
                     or (self.peer_name == "guardian" and name == "authorize_action"))):
                raise BrainError("AUDIT_LOG_UNAVAILABLE", "Brain cannot record the required MCP exchange")

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
                        # Only the agreed absence code permits a verdict-availability
                        # retry. A generic tool crash must remain an ordinary failure.
                        if name == "get_trust_verdict" and message.strip() in {
                            "verdict_not_found",
                            "Error executing tool get_trust_verdict: verdict_not_found",
                            "Error calling tool 'get_trust_verdict': verdict_not_found",
                        }:
                            raise BrainError("GUARDIAN_VERDICT_NOT_READY",
                                             "Guardian has not scored the required evidence")
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
            result = await asyncio.wait_for(request(), self.timeout_seconds)
        except BrainError as error:
            if self.journal is not None:
                self.journal.append({
                    **event_context, "event": "mcp_tool_response_received", "peer": self.peer_name, "tool": name,
                    **refs, "outcome": "failure", "code": error.code,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                })
            raise
        except TimeoutError:
            if self.journal is not None:
                self.journal.append({
                    **event_context, "event": "mcp_tool_response_received", "peer": self.peer_name, "tool": name,
                    **refs, "outcome": "failure", "code": "PEER_TIMEOUT",
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                })
            raise BrainError("PEER_TIMEOUT", "Peer call timed out") from None
        except ExceptionGroup as group:

            def leaves(error):
                if isinstance(error, BaseExceptionGroup):
                    return [leaf for child in error.exceptions for leaf in leaves(child)]
                return [error]

            errors = leaves(group)
            refusal = next((error for error in errors if isinstance(error, BrainError)), None)
            if refusal is not None:
                if self.journal is not None:
                    self.journal.append({
                        **event_context, "event": "mcp_tool_response_received", "peer": self.peer_name, "tool": name,
                        **refs, "outcome": "failure", "code": refusal.code,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    })
                raise refusal from None
            if any(isinstance(error, TimeoutError) for error in errors):
                if self.journal is not None:
                    self.journal.append({
                        **event_context, "event": "mcp_tool_response_received", "peer": self.peer_name, "tool": name,
                        **refs, "outcome": "failure", "code": "PEER_TIMEOUT",
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    })
                raise BrainError("PEER_TIMEOUT", "Peer call timed out") from None
            if self.journal is not None:
                self.journal.append({
                    **event_context, "event": "mcp_tool_response_received", "peer": self.peer_name, "tool": name,
                    **refs, "outcome": "failure", "code": "PEER_UNAVAILABLE",
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                })
            raise BrainError(
                "PEER_UNAVAILABLE", "Peer transport or response is unavailable"
            ) from None
        except Exception:
            if self.journal is not None:
                self.journal.append({
                    **event_context, "event": "mcp_tool_response_received", "peer": self.peer_name, "tool": name,
                    **refs, "outcome": "failure", "code": "PEER_UNAVAILABLE",
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                })
            raise BrainError(
                "PEER_UNAVAILABLE", "Peer transport or response is unavailable"
            ) from None
        if self.journal is not None:
            self.journal.append({
                **event_context, "event": "mcp_tool_response_received", "peer": self.peer_name, "tool": name,
                **self._event_refs(result), "outcome": "success",
                "response_summary": self._event_summary(result, response=True),
                "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            })
        return result

    @staticmethod
    def _event_summary(payload, *, response=False):
        if not isinstance(payload, dict):
            return {}
        fields = ({
            "run_id", "tick", "reading_id", "reading_ids", "source_reading_ids",
            "device_id", "device_ids", "node_id", "node_ids", "action", "targets",
            "params", "risk", "risk_level", "domain", "idempotency_key", "state",
            "event_id", "fresh", "count", "unit_type", "scenario_id",
        } if not response else {
            "run_id", "tick", "status", "code", "decision", "decision_id", "accepted",
            "duplicate", "invalidated", "trust_score", "score", "scale", "caused_by",
            "reading_id", "valid_until_tick", "would_pass_checks", "blocked_by", "safe",
            "protocol_version", "outcome",
        })
        result = {key: value for key, value in payload.items() if key in fields}
        return {key: list(value[:100]) if isinstance(value, (list, tuple)) else value
                for key, value in result.items()}

    @staticmethod
    def _event_refs(payload):
        if not isinstance(payload, dict):
            return {}
        keys = {
            "run_id", "tick", "reading_id", "reading_ids", "source_reading_ids",
            "device_id", "device_ids", "node_id", "node_ids", "action_id", "jti",
            "idempotency_key",
        }
        return {key: value for key, value in payload.items() if key in keys}


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
        result = {key: at_path(reply, path) for key, path in spec["response_fields"].items()}
        # Approval and refusal have different optional fields. Keep missing mandatory
        # fields fatal, but do not turn an ordinary denial into a schema failure.
        for key, path in spec.get("optional_response_fields", {}).items():
            try:
                value = at_path(reply, path)
            except BrainError:
                continue
            result[key] = value
        return result
