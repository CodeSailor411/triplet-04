"""Local HTTP servers for explicit transport tests, never production partner services."""
import contextlib
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from civis_brain.errors import BrainError
from civis_mock_peers.peers import FixtureTwin


@contextlib.contextmanager
def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        sock.close()


def peer_app(peer, key):
    mcp = MCPServer("local-contract-fixture")

    async def call(ctx, name, arguments):
        if ctx.request_context.request.headers.get("authorization") != f"Bearer {key}":
            raise ToolError("UNAUTHENTICATED: incorrect local test credential")
        try:
            return await peer.call_tool(name, arguments)
        except BrainError as error:
            raise ToolError(f"{error.code}: {error.message}") from None

    @mcp.tool()
    async def get_capabilities(ctx: Context) -> dict:
        return await call(ctx, "get_capabilities", {})

    if isinstance(peer, FixtureTwin):
        @mcp.tool()
        async def get_clock(ctx: Context) -> dict:
            return await call(ctx, "get_clock", {})

        @mcp.tool()
        async def list_nodes(ctx: Context) -> dict:
            return await call(ctx, "list_nodes", {})

        @mcp.tool()
        async def list_actions(ctx: Context) -> dict:
            return await call(ctx, "list_actions", {})

        @mcp.tool()
        async def get_containment_state(ctx: Context) -> dict:
            return await call(ctx, "get_containment_state", {})

        @mcp.tool()
        async def get_readings(ctx: Context) -> dict:
            if ctx.request_context.request.headers.get("authorization") != f"Bearer {key}":
                raise ToolError("UNAUTHENTICATED: incorrect local test credential")
            return peer.clock

        @mcp.tool()
        async def fixture_preview(ctx: Context, action: str, targets: list[str], params: dict) -> dict:
            return await call(ctx, "fixture_preview", dict(
                action=action, targets=targets, params=params))

        @mcp.tool()
        async def actuate(ctx: Context, action: str, targets: list[str], params: dict,
                          token: str, idempotency_key: str) -> dict:
            return await call(ctx, "actuate", dict(
                action=action, targets=targets, params=params, token=token,
                idempotency_key=idempotency_key))
    else:
        @mcp.tool()
        async def fixture_score(ctx: Context, run_id: str, tick: int, readings: list[dict]) -> dict:
            return await call(ctx, "fixture_score", dict(run_id=run_id, tick=tick, readings=readings))

        @mcp.tool()
        async def fixture_approve(ctx: Context, run_id: str, tick: int, time: str, action: str,
                                  targets: list[str], params: dict, risk: str,
                                  source_reading_ids: list[str]) -> dict:
            return await call(ctx, "fixture_approve", dict(
                run_id=run_id, tick=tick, time=time, action=action, targets=targets, params=params,
                risk=risk, source_reading_ids=source_reading_ids))

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/", mcp.streamable_http_app())
    return app
