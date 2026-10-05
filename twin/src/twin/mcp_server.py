"""The Twin's MCP tools. Built with the official `mcp` SDK (class MCPServer, formerly FastMCP).

Right now: get_capabilities, list_nodes, run_scenario (stub, hidden).
Next (see the plan): read tools, actuate, containment tools, real scenario engine.
"""
from importlib.metadata import version as pkg_version
from typing import Literal

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel

from . import __version__
from .auth import HIDDEN_TOOLS, TOOL_ACCESS, Identity, KeyRing, token_from_headers
from .models import Node, Topology

Domain = Literal["traffic", "water", "power", "air_quality", "emergency"]


class Capabilities(BaseModel):
    layer: str
    layer_version: str
    mcp_sdk_version: str
    protocol_version: str
    authenticated_as: str | None     # None means the key was missing or unknown
    tools_you_can_call: list[str]


class NodeList(BaseModel):
    seed: int
    count: int
    nodes: list[Node]


def _identity(ctx: ServerRequestContext, keyring: KeyRing) -> Identity | None:
    request = ctx.request                           # the HTTP request this message came in on
    return keyring.identify(token_from_headers(request.headers)) if request is not None else None


def build_mcp(topology: Topology, keyring: KeyRing) -> MCPServer:
    mcp = MCPServer(
        "twin",
        title="Twin: simulated city",
        instructions="Simulated city for TSYP14 Triplet 04. Send 'Authorization: Bearer <your key>'. "
                     "Call get_capabilities first.",
        version=__version__,
    )

    def caller(ctx: Context) -> Identity | None:
        return _identity(ctx.request_context, keyring)

    def require(ctx: Context, tool: str) -> Identity:
        """Clear errors: not logged in is different from logged in but not allowed."""
        who = caller(ctx)
        if who is None:
            raise ToolError("UNAUTHENTICATED: missing or unknown key. Send 'Authorization: Bearer <your key>'.")
        allowed = TOOL_ACCESS[tool]
        if allowed is not None and who not in allowed:
            raise ToolError(f"FORBIDDEN: '{who.value}' may not call {tool}.")
        return who

    @mcp.tool()
    def get_capabilities(ctx: Context) -> Capabilities:
        """What this Twin is, which versions it runs, who you are logged in as, and which tools you can call.
        Works without a key, so a wrong key can be diagnosed in one call."""
        who = caller(ctx)
        visible = [t for t, allowed in TOOL_ACCESS.items()
                   if t not in HIDDEN_TOOLS or (who is not None and allowed is not None and who in allowed)]
        return Capabilities(
            layer="twin", layer_version=__version__, mcp_sdk_version=pkg_version("mcp"),
            protocol_version=ctx.request_context.protocol_version,
            authenticated_as=who.value if who else None, tools_you_can_call=visible)

    @mcp.tool()
    def list_nodes(ctx: Context, domain: Domain | None = None) -> NodeList:
        """List the nodes of the city (id, domains, zone, position, sensors with units, actuators, neighbours).
        Optionally only one domain. Never includes normal ranges: the Twin publishes no datasheet."""
        require(ctx, "list_nodes")
        nodes = [n for n in topology.nodes if domain is None or domain in n.domains]
        return NodeList(seed=topology.seed, count=len(nodes), nodes=nodes)

    @mcp.tool()
    def run_scenario(ctx: Context, name: str) -> dict:
        """Start a scenario by name. Hidden: only visible to a caller with the scenario key."""
        require(ctx, "run_scenario")
        raise ToolError(f"NOT_IMPLEMENTED: the scenario engine arrives on 8 Oct (asked for '{name}').")

    async def access_filter(ctx: ServerRequestContext, call_next):
        """Hides tools from callers who may not use them (tool list and tool calls)."""
        who = _identity(ctx, keyring)

        def visible(tool_name: str) -> bool:
            if tool_name not in HIDDEN_TOOLS:
                return True
            allowed = TOOL_ACCESS.get(tool_name)
            return who is not None and allowed is not None and who in allowed

        if ctx.method == "tools/call":
            name = (ctx.params or {}).get("name", "")
            if not visible(name):
                # Exactly what the SDK answers for a tool that does not exist (a tool-level error result),
                # so a caller cannot tell "hidden" from "not there".
                return CallToolResult(content=[TextContent(type="text", text=f"Unknown tool: {name}")], is_error=True)
        result = await call_next(ctx)
        if ctx.method == "tools/list":
            def keep(t) -> bool:
                return visible(t["name"] if isinstance(t, dict) else t.name)
            if isinstance(result, dict):
                result["tools"] = [t for t in result["tools"] if keep(t)]
            else:
                result.tools = [t for t in result.tools if keep(t)]
        return result

    mcp.middleware.append(access_filter)
    return mcp
