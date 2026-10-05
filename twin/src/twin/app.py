"""The FastAPI app: MCP mounted at "/", plus plain routes for health and the live SSE feed.

Run:  python -m uvicorn --factory twin.app:create_app --port 8000
"""
import asyncio
import contextlib
import json
import logging

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from . import __version__
from .auth import LAYERS, KeyRing, token_from_headers
from .generator import fingerprint, generate
from .mcp_server import build_mcp
from .settings import Settings, load_settings
from .util import now_iso

log = logging.getLogger("twin")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    cfg = settings.config
    keyring = KeyRing.from_secrets(settings.secrets)
    topology, layout = generate(cfg)
    log.info("Twin %s: seed %s, city fingerprint %s, %d nodes", __version__, cfg.seed,
             fingerprint(topology), len(topology.nodes))

    mcp = build_mcp(topology, keyring)
    mcp_app = mcp.streamable_http_app()                # the MCP endpoint lives at /mcp inside this app

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp.session_manager.run():          # a mounted sub-app does not start its own lifespan
            yield

    app = FastAPI(title="Twin", version=__version__, lifespan=lifespan)
    app.state.settings, app.state.topology, app.state.layout, app.state.keyring = settings, topology, layout, keyring

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "twin", "version": __version__, "seed": cfg.seed,
                "city_fingerprint": fingerprint(topology), "nodes": len(topology.nodes), "time": now_iso()}

    @app.get("/events")
    async def events(request: Request, max_events: int | None = Query(None, ge=1, le=1000)):
        """Live feed (SSE). Right now: a hello event and heartbeats. Readings arrive on 6 Oct.
        max_events closes the stream after that many events (for tests and quick checks)."""
        who = keyring.identify(token_from_headers(request.headers))
        if who is None:
            return _error(401, "UNAUTHENTICATED", "Missing or unknown key. Send 'Authorization: Bearer <your key>'.")
        if who not in LAYERS:
            return _error(403, "FORBIDDEN", f"'{who.value}' may not read the live feed.")

        async def stream():
            sent = 0
            yield {"event": "hello", "data": json.dumps({"service": "twin", "seed": cfg.seed,
                                                         "you_are": who.value, "time": now_iso()})}
            sent += 1
            while max_events is None or sent < max_events:
                await asyncio.sleep(cfg.sse.heartbeat_seconds)
                yield {"event": "heartbeat", "data": json.dumps({"time": now_iso()})}
                sent += 1

        return EventSourceResponse(stream())

    app.mount("/", mcp_app)                            # last, so the routes above win
    return app
