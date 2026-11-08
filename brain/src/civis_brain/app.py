"""Brain mock MCP server, with explicit partial readiness and layer authentication."""

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from civis_brain import __version__
from civis_brain.contracts import Capabilities, ContainmentNotice, DecisionBatch, ReadingsBatch
from civis_brain.debug import attach_debug
from civis_brain.integration.bootstrap import configured_runtime
from civis_brain.integration.feed import TwinFeed
from civis_brain.integration.runtime import BrainRuntime
from civis_brain.integration.service import bind_runtime
from civis_brain.scenarios.registry import DETECTION_ONLY_SCENARIOS, IMPLEMENTED_SCENARIOS
from civis_brain.settings import Settings, load_settings

IMPLEMENTED_TOOLS = [
    "get_capabilities",
    "evaluate_tick",
    "get_active_incidents",
    "explain_decision",
    "notify_containment",
]


def create_app(settings: Settings | None = None, runtime: BrainRuntime | None = None) -> FastAPI:
    settings = settings or load_settings()
    runtime = runtime or configured_runtime(settings)
    if runtime.journal.run_log_dir is None:
        runtime.journal.run_log_dir = Path(settings.brain_config_root).resolve() / "logs"
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

    def require(ctx: Context, allowed: set[str], tool_name: str) -> str:
        caller = identity(ctx)
        if caller is None:
            runtime.journal.append({
                "event": "brain_request_rejected", "tool": tool_name,
                "caller": None, "code": "UNAUTHENTICATED",
            })
            runtime.journal.append({
                "event": "brain_response_sent", "tool": tool_name,
                "outcome": "failure", "code": "UNAUTHENTICATED",
            })
            raise ToolError("UNAUTHENTICATED: send your layer's Bearer key")
        if caller not in allowed:
            runtime.journal.append({
                "event": "brain_request_rejected", "tool": tool_name,
                "caller": caller, "code": "FORBIDDEN",
            })
            runtime.journal.append({
                "event": "brain_response_sent", "tool": tool_name, "caller": caller,
                "outcome": "failure", "code": "FORBIDDEN",
            })
            raise ToolError("FORBIDDEN: this layer may not call this tool")
        return caller

    def record_request(ctx: Context, tool_name: str, **details) -> None:
        runtime.journal.append({
            "event": "brain_request_received", "tool": tool_name,
            "caller": identity(ctx), **details,
        })

    def record_response(tool_name: str, *, run_id=None, tick=None, **details) -> None:
        runtime.journal.append({
            "event": "brain_response_sent", "tool": tool_name,
            "run_id": run_id, "tick": tick, **details,
        })

    def record_failure(tool_name: str, error: Exception, *, run_id=None, tick=None) -> None:
        runtime.journal.append({
            "event": "brain_response_sent", "tool": tool_name, "run_id": run_id,
            "tick": tick, "outcome": "failure",
            "code": getattr(error, "code", "INTERNAL_ERROR"),
        })

    @mcp.tool()
    def get_capabilities(ctx: Context) -> Capabilities:
        """Report implemented tools; full partner integration remains unverified."""
        record_request(ctx, "get_capabilities")
        try:
            result = Capabilities.model_validate(
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
        except Exception as error:
            record_failure("get_capabilities", error)
            raise
        record_response("get_capabilities", outcome="success", tool_count=len(IMPLEMENTED_TOOLS))
        return result

    @mcp.tool()
    async def evaluate_tick(ctx: Context, batch: ReadingsBatch) -> DecisionBatch:
        """Evaluate candidate evidence through shared trust and response checks."""
        record_request(
            ctx, "evaluate_tick", run_id=batch.run_id, tick=batch.tick, timestamp=batch.time,
            count=batch.count, reading_ids=[row.reading_id for row in batch.readings],
        )
        require(ctx, {"twin", "guardian", "scenario"}, "evaluate_tick")
        try:
            if getattr(runtime.twin, "is_fixture", False):
                # Fixture mode uses the supplied simulated clock, never a live clock claim.
                runtime.twin.advance(batch)
            result = await runtime.evaluate_tick(batch)
        except Exception as error:
            record_failure("evaluate_tick", error, run_id=batch.run_id, tick=batch.tick)
            raise
        record_response(
            "evaluate_tick", run_id=batch.run_id, tick=batch.tick, outcome="success",
            decision_count=len(result.decisions), statuses=[row.status for row in result.decisions],
        )
        return result

    @mcp.tool()
    def get_active_incidents(ctx: Context, run_id: str) -> dict:
        """Read active candidates for the specified run."""
        record_request(ctx, "get_active_incidents", run_id=run_id)
        require(ctx, {"twin", "guardian", "scenario"}, "get_active_incidents")
        try:
            result = runtime.get_active_incidents(run_id)
        except Exception as error:
            record_failure("get_active_incidents", error, run_id=run_id)
            raise
        record_response("get_active_incidents", run_id=run_id, outcome="success",
                        incident_count=len(result.get("incidents", [])))
        return result

    @mcp.tool()
    def explain_decision(ctx: Context, decision_id: str) -> dict:
        """Read a saved decision with evidence IDs and redacted peer detail."""
        record_request(ctx, "explain_decision", decision_id=decision_id)
        require(ctx, {"twin", "guardian", "scenario"}, "explain_decision")
        try:
            result = runtime.explain_decision(decision_id)
        except Exception as error:
            record_failure("explain_decision", error)
            raise
        decision = result.get("decision") or {}
        record_response("explain_decision", run_id=decision.get("run_id"),
                        tick=decision.get("tick"), outcome="success", found=result.get("found"))
        return result

    @mcp.tool()
    def notify_containment(ctx: Context, notice: ContainmentNotice) -> dict:
        """Guardian-only invalidation callback; Brain performs no containment operation."""
        record_request(
            ctx, "notify_containment", run_id=notice.run_id, event_id=notice.event_id,
            state=notice.state, device_ids=notice.device_ids, reading_ids=notice.reading_ids,
        )
        require(ctx, {"guardian"}, "notify_containment")
        try:
            result = runtime.notify_containment(notice)
        except Exception as error:
            record_failure("notify_containment", error, run_id=notice.run_id)
            raise
        record_response("notify_containment", run_id=notice.run_id,
                        outcome="success" if result.get("accepted") else "refused",
                        accepted=result.get("accepted"), invalidated=result.get("invalidated"),
                        code=result.get("code"))
        return result

    transport_security = None
    if settings.brain_mcp_allowed_hosts:
        local_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
        transport_security = TransportSecuritySettings(
            allowed_hosts=[*local_hosts, *settings.brain_mcp_allowed_hosts],
            allowed_origins=[f"{scheme}://{host}"
                             for scheme in ("http", "https") for host in local_hosts],
        )
    mcp_app = mcp.streamable_http_app(transport_security=transport_security)
    feed = None
    if settings.twin_feed_enabled:
        if settings.peer_mode != "live":
            raise ValueError("Twin SSE requires live peer mode")
        persistence = (policy.get("persistence_ticks") for sid, policy in runtime.policies.items()
                       if sid in runtime.enabled)
        catch_up_ticks = max((ticks for ticks in persistence if type(ticks) is int and 1 <= ticks <= 100),
                             default=2)
        feed = TwinFeed(runtime, settings.twin_events_url, settings.twin_brain_key,
                        catch_up_ticks=max(2, catch_up_ticks))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.journal.append({"event": "brain_service_started", "peer_mode": settings.peer_mode})
        try:
            async with mcp.session_manager.run():
                if feed:
                    feed.start()
                try:
                    yield
                finally:
                    if feed:
                        await feed.close()
        finally:
            await runtime.close()
            runtime.journal.append({"event": "brain_service_stopped"})

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
            "llm_mode": settings.llm_mode,
            "guardian_transport": settings.guardian_transport,
            "guardian_contract_confirmed": settings.guardian_contract_confirmed,
            "browser_presets": "isolated fixtures, not the live feed",
            "implemented_scenarios": list(IMPLEMENTED_SCENARIOS),
            "awaiting_scenarios": list(DETECTION_ONLY_SCENARIOS),
            "feed": feed.status if feed else {"state": "disabled"},
            "mock_integration_profile": settings.mock_integration_profile,
            "event_log": runtime.journal.logging_status,
        }

    if settings.brain_debug_enabled:
        attach_debug(app, runtime, settings)
    app.mount("/", mcp_app)
    return app
