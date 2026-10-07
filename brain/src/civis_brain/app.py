"""Runnable transport scaffold. Workflow tools honestly return NOT_IMPLEMENTED."""

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from civis_brain import __version__
from civis_brain.contracts import Capabilities, ContainmentNotice, ReadingsBatch
from civis_brain.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    mcp = MCPServer("civis_brain", version=__version__)

    def identity(ctx: Context) -> str | None:
        request = ctx.request_context.request
        bearer = request.headers.get("authorization", "") if request is not None else ""
        if not bearer.startswith("Bearer "):
            return None
        token = bearer[7:]
        for caller, expected in {
            "twin": settings.brain_twin_caller_key,
            "guardian": settings.brain_guardian_caller_key,
            "scenario": settings.brain_scenario_key,
        }.items():
            if expected and secrets.compare_digest(token, expected):
                return caller
        return None

    def require(ctx: Context, allowed: set[str]) -> str:
        caller = identity(ctx)
        if caller is None:
            raise ToolError("UNAUTHENTICATED: send your layer's Bearer key")
        if caller not in allowed:
            raise ToolError("FORBIDDEN: this layer may not call this tool")
        return caller

    @mcp.tool()
    def get_capabilities(ctx: Context) -> Capabilities:
        """Report scaffold readiness and negotiated protocol without exposing keys."""
        return Capabilities.model_validate({
            "layer": "city_brain", "layer_version": __version__, "ready": False,
            "protocol_version": ctx.request_context.protocol_version,
            "required_protocol_version": "2026-07-28",
            "authenticated_as": identity(ctx), "implemented_tools": ["get_capabilities"],
            "planned_tools": ["evaluate_tick", "get_active_incidents", "explain_decision",
                              "notify_containment"],
        })

    @mcp.tool()
    async def evaluate_tick(ctx: Context, batch: ReadingsBatch) -> dict:
        """Proposed mock trigger. Business workflow is assigned to Elyes and the team."""
        require(ctx, {"twin", "guardian", "scenario"})
        raise ToolError("NOT_IMPLEMENTED: the team has not delivered evaluate_tick yet")

    @mcp.tool()
    def get_active_incidents(ctx: Context, run_id: str) -> dict:
        """Planned read-only incident view for partner workflow tests."""
        require(ctx, {"twin", "guardian", "scenario"})
        raise ToolError("NOT_IMPLEMENTED: incident state is assigned to Elyes")

    @mcp.tool()
    def explain_decision(ctx: Context, decision_id: str) -> dict:
        """Planned explanation and evidence references for a saved decision."""
        require(ctx, {"twin", "guardian", "scenario"})
        raise ToolError("NOT_IMPLEMENTED: decision log is assigned to Elyes")

    @mcp.tool()
    def notify_containment(ctx: Context, notice: ContainmentNotice) -> dict:
        """Guardian-only proposed callback for invalidating affected Brain evidence."""
        require(ctx, {"guardian"})
        raise ToolError("NOT_IMPLEMENTED: containment callback is assigned to Elyes")

    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="CIVIS Brain mock scaffold", version=__version__, lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "scaffold", "ready": False, "service": "city_brain",
                "version": __version__}

    app.mount("/", mcp_app)
    return app
