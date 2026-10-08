"""Shared test setup: a real Twin running on a free port in a background thread."""
import contextlib
import socket
import threading
import time

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from twin.app import create_app
from twin.settings import Secrets, Settings, load_config

KEYS = {"city_brain": "brain-test-key", "guardian": "guardian-test-key", "scenario": "scenario-test-key"}


@pytest.fixture(scope="session")
def config():
    cfg = load_config()
    cfg.sse.heartbeat_seconds = 0.05          # fast heartbeats so the SSE test finishes quickly
    cfg.clock.autorun = False                 # the clock stands still, so tests control time
    return cfg


@pytest.fixture(scope="session")
def settings(config):
    return Settings(config=config, secrets=Secrets(**KEYS))


@contextlib.contextmanager
def run_twin(settings):
    """A real Twin on a free port in a background thread. Yields (url, app)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "test server did not start"
    try:
        yield f"http://127.0.0.1:{port}", app
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def base_url(settings):
    """Twin with a standing-still clock (tick 0 forever)."""
    with run_twin(settings) as (url, _app):
        yield url


@pytest.fixture(scope="session")
def running_url(config):
    """Twin whose clock runs fast (a tick every 50 ms real time), for tests of the live feed."""
    cfg = config.model_copy(deep=True)
    cfg.clock.autorun = True
    cfg.clock.speed = 20.0                    # 1 simulated second per tick / 20 = 50 ms real
    cfg.sse.heartbeat_seconds = 5
    with run_twin(Settings(config=cfg, secrets=Secrets(**KEYS))) as (url, _app):
        yield url


@pytest.fixture
def mcp_client(base_url):
    """Usage: async with mcp_client('city_brain') as c, or mcp_client(None) for no key."""
    @contextlib.asynccontextmanager
    async def make(identity: str | None, key: str | None = None):
        token = key if key is not None else (KEYS[identity] if identity else None)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        http = httpx2.AsyncClient(headers=headers)
        async with Client(streamable_http_client(base_url + "/mcp", http_client=http)) as client:
            yield client
    return make
