"""Brain mock MCP server, with explicit partial readiness and layer authentication."""

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from civis_brain import __version__
from civis_brain.contracts import Capabilities, ContainmentNotice, DecisionBatch, ReadingsBatch
from civis_brain.debug import attach_debug
from civis_brain.integration.bootstrap import configured_runtime
from civis_brain.integration.runtime import BrainRuntime
from civis_brain.integration.service import bind_runtime
from civis_brain.settings import Settings

IMPLEMENTED_TOOLS = [
    "get_capabilities",
    "evaluate_tick",
    "get_active_incidents",
    "explain_decision",
    "notify_containment",
]


def create_app(settings: Settings | None = None, runtime: BrainRuntime | None = None) -> FastAPI:
    settings = settings or Settings()
    runtime = runtime or configured_runtime(settings)
    bind_runtime(runtime)
    mcp = MCPServer("civis_brain", version=__version__)
    keys = [
        settings.brain_twin_caller_key,
        settings.brain_guardian_caller_key,
        settings.brain_scenario_key,
    ]
    if any(not key for key in keys) or len(set(keys)) != 3:
        raise ValueError("Each Brain caller must have a distinct nonempty key")

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
            if secrets.compare_digest(token, expected):
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
        """Report implemented tools; the five-scenario release remains incomplete."""
        return Capabilities.model_validate(
            {
                "layer": "city_brain",
                "layer_version": __version__,
                "ready": False,
                "protocol_version": ctx.request_context.protocol_version,
                "required_protocol_version": "2026-07-28",
                "authenticated_as": identity(ctx),
                "implemented_tools": IMPLEMENTED_TOOLS,
                "planned_tools": [],
            }
        )

    @mcp.tool()
    async def evaluate_tick(ctx: Context, batch: ReadingsBatch) -> DecisionBatch:
        """Evaluate candidate evidence through shared trust and response checks."""
        require(ctx, {"twin", "guardian", "scenario"})
        if getattr(runtime.twin, "is_fixture", False):
            # Fixture mode uses the supplied simulated clock, never a live clock claim.
            runtime.twin.advance(batch)
        return await runtime.evaluate_tick(batch)

    @mcp.tool()
    def get_active_incidents(ctx: Context, run_id: str) -> dict:
        """Read active candidates for the specified run."""
        require(ctx, {"twin", "guardian", "scenario"})
        return runtime.get_active_incidents(run_id)

    @mcp.tool()
    def explain_decision(ctx: Context, decision_id: str) -> dict:
        """Read a saved decision with evidence IDs and redacted peer detail."""
        require(ctx, {"twin", "guardian", "scenario"})
        return runtime.explain_decision(decision_id)

    @mcp.tool()
    def notify_containment(ctx: Context, notice: ContainmentNotice) -> dict:
        """Guardian-only invalidation callback; Brain performs no containment operation."""
        require(ctx, {"guardian"})
        return runtime.notify_containment(notice)

    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp.session_manager.run():
            yield
        await runtime.close()

    app = FastAPI(title="CIVIS Brain primary mock", version=__version__, lifespan=lifespan)
    app.state.runtime = runtime

    @app.get("/health")
    async def health():
        return {
            "status": "partial",
            "ready": False,
            "service": "city_brain",
            "version": __version__,
            "peer_mode": settings.peer_mode,
            "implemented_scenarios": ["S03", "S04"],
            "awaiting_scenarios": ["S01", "S02", "S05"],
        }

    if settings.brain_debug_enabled:
        attach_debug(app, runtime, settings)
    app.mount("/", mcp_app)
    return app
