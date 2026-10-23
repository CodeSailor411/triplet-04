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
from .actions import ActionBook
from .containment import ContainmentBook
from .scenarios import ScenarioBook
from .runlog import RunLog
from .settings import Settings, load_settings
from .sim import Simulation
from .util import now_iso

log = logging.getLogger("twin")

MAX_BACKLOG = 100       # a slow feed reader may fall this many ticks behind before it skips ahead


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    cfg = settings.config
    keyring = KeyRing.from_secrets(settings.secrets)
    topology, layout = generate(cfg)
    log.info("Twin %s: seed %s, city fingerprint %s, %d nodes", __version__, cfg.seed,
             fingerprint(topology), len(topology.nodes))

    sim = Simulation(topology, cfg)
    book = ActionBook(topology, cfg, sim)
    containment = ContainmentBook(topology, cfg, sim)
    sim.overlay, book.containment = containment, containment
    scenarios = ScenarioBook(sim)
    sim.faults = scenarios
    runlog = RunLog(cfg.logging, sim, scenarios, {"seed": cfg.seed, "city_fingerprint": fingerprint(topology),
                                                  "nodes": len(topology.nodes), "tick_seconds": cfg.clock.tick_seconds,
                                                  "twin_version": __version__})
    book.recorder = containment.recorder = scenarios.recorder = runlog
    mcp = build_mcp(topology, keyring, sim, book, containment, scenarios)
    if cfg.tokens.mode == "unsigned":
        log.warning("TOKENS ARE UNSIGNED (tokens.mode: unsigned). Fine for mocks and the hand-over, not for v1.0.")
    mcp_app = mcp.streamable_http_app()                # the MCP endpoint lives at /mcp inside this app

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        ticker = asyncio.create_task(sim.run_forever()) if cfg.clock.autorun else None
        follower = asyncio.create_task(runlog.follow_clock()) if runlog.enabled else None
        runlog.record("scenario", {"phase": "twin_started"})            # opens the run's part file, also after a restart
        try:
            async with mcp.session_manager.run():      # a mounted sub-app does not start its own lifespan
                yield
        finally:
            if follower:
                follower.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await follower
            runlog.end_run()                              # closing line and the merged file
            if ticker:
                ticker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ticker

    app = FastAPI(title="Twin", version=__version__, lifespan=lifespan)
    app.state.settings, app.state.topology, app.state.layout, app.state.keyring = settings, topology, layout, keyring
    app.state.sim, app.state.book, app.state.containment = sim, book, containment
    app.state.scenarios, app.state.runlog = scenarios, runlog

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "twin", "version": __version__, "seed": cfg.seed,
                "city_fingerprint": fingerprint(topology), "nodes": len(topology.nodes), "time": now_iso(),
                "run_id": sim.run_id, "tick": sim.tick, "sim_time": sim.clock.iso_of(sim.tick)}

    @app.get("/events")
    async def events(request: Request, max_events: int | None = Query(None, ge=1, le=1000)):
        """Live feed (SSE). Events: `hello` once, then one `readings` event per tick (all readings of that
        tick), plus a `heartbeat` whenever nothing happened for a while. A client that connects starts at the
        current tick. A client that falls more than MAX_BACKLOG ticks behind skips ahead (the event says how many).
        max_events closes the stream after that many events (for tests and quick checks)."""
        who = keyring.identify(token_from_headers(request.headers))
        if who is None:
            return _error(401, "UNAUTHENTICATED", "Missing or unknown key. Send 'Authorization: Bearer <your key>'.")
        if who not in LAYERS:
            return _error(403, "FORBIDDEN", f"'{who.value}' may not read the live feed.")

        async def stream():
            sent = 0
            yield {"event": "hello", "data": json.dumps({"service": "twin", "seed": cfg.seed, "you_are": who.value,
                                                         "run_id": sim.run_id, "tick": sim.tick, "time": now_iso()})}
            sent += 1
            run_number, last = sim.run_number, sim.tick       # everything up to and including `last` counts as seen
            while max_events is None or sent < max_events:
                if not await sim.wait_for_change(run_number, last, cfg.sse.heartbeat_seconds):
                    yield {"event": "heartbeat", "data": json.dumps({"time": now_iso()})}
                    sent += 1
                    continue
                if sim.run_number != run_number:               # a new run started: begin at its current tick
                    run_number, last = sim.run_number, sim.tick - 1
                first, skipped = last + 1, 0
                if sim.tick - last > MAX_BACKLOG:
                    first, skipped = sim.tick, sim.tick - last - 1
                for tick in range(first, sim.tick + 1):
                    batch = sim.readings_at(tick)
                    payload = batch.model_dump()
                    if skipped:
                        payload["skipped_ticks"] = skipped
                        skipped = 0
                    yield {"event": "readings", "id": f"{batch.run_id}:{tick}", "data": json.dumps(payload)}
                    sent += 1
                    if max_events is not None and sent >= max_events:
                        return
                last = sim.tick

        return EventSourceResponse(stream())

    app.mount("/", mcp_app)                            # last, so the routes above win
    return app
