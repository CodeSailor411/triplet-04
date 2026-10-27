"""Live sensor values for the dashboard (added 27 Oct).

Until now the dashboard only re-read the run logs, and the Twin logs only the readings an attack touched. So a calm Twin
looked dead. This module adds a second source: the Twin's own live feed (`/events`, SSE = a stream the server keeps
pushing over one open HTTP connection). It keeps the LATEST value of every sensor and nothing else: no history, no
writing to disk. The timeline and the map still come from the run logs.

It never raises: if the Twin is down, refuses the key, or goes quiet, it records why, waits, and tries again.
The Twin's `/events` accepts the City Brain's and Guardian's keys, so the dashboard borrows one of them (the City Brain's
by default). A key of its own would be cleaner, but it would change the permission table the partners reviewed.
"""
import asyncio
import json
import logging
import time
from typing import Any

import httpx2

from ..settings import TWIN_ROOT

log = logging.getLogger("twin.dashboard.live")

RETRY_SECONDS = 2.0          # wait before reconnecting after the stream ended or failed
REFUSED_RETRY_SECONDS = 10.0 # a refused key will not fix itself in two seconds, so do not hammer the Twin
QUIET_AFTER_SECONDS = 5.0    # no readings for this long (real seconds): the chip says "quiet" instead of "live"
READ_TIMEOUT_SECONDS = 30.0  # the Twin sends a heartbeat every 15 s, so 30 s of silence means the stream is dead


def find_key(cli_value: str | None = None) -> str | None:
    """The key the dashboard sends: --feed-key, else TWIN_KEY_CITY_BRAIN from the environment, else from twin/.env."""
    import os
    if cli_value:
        return cli_value
    if os.environ.get("TWIN_KEY_CITY_BRAIN"):
        return os.environ["TWIN_KEY_CITY_BRAIN"]
    try:
        for line in (TWIN_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            name, _, value = line.strip().partition("=")
            if name.strip() == "TWIN_KEY_CITY_BRAIN" and value.strip():
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return None


class LiveFeed:
    def __init__(self, base_url: str, key: str | None):
        self.url = base_url.rstrip("/") + "/events"
        self.key = key
        self.latest: dict[str, dict[str, Any]] = {}      # device_id (or device_id/channel) -> newest reading
        self.run_id: str | None = None
        self.tick: int | None = None
        self.sim_time: str | None = None
        self.count = 0                                   # how many readings the latest tick carried
        self.connected = False
        self.error: str | None = None
        self.version = 0                                 # goes up with every readings event (the page watches this)
        self.last_event = 0.0                            # time.monotonic() of the last readings event
        self.enabled = key is not None
        if key is None:
            self.error = "no key (set TWIN_KEY_CITY_BRAIN, or pass --feed-key)"

    # ------------------------------------------------------------------ what the page asks
    def status(self) -> tuple[str, bool]:
        """(text for the chip, is it live?)"""
        if not self.enabled:
            return f"feed off: {self.error}", False
        if not self.connected:
            return f"feed lost: {self.error or 'connecting'}", False
        if time.monotonic() - self.last_event > QUIET_AFTER_SECONDS:
            return f"feed quiet (last tick {self.tick})", False
        return f"LIVE · tick {self.tick}", True

    def node_values(self, node_id: str) -> list[dict[str, Any]]:
        """The latest readings of one node, sorted by device. Each: device_id, sensor, channel, value, unit, tick."""
        rows = [r for r in self.latest.values() if r["node_id"] == node_id]
        return sorted(rows, key=lambda r: (r["device_id"], r.get("channel") or ""))

    # ------------------------------------------------------------------ the loop
    async def run(self) -> None:
        """Run forever (start it as a background task). Cancel it to stop."""
        if not self.enabled:
            return
        while True:
            wait = RETRY_SECONDS
            try:
                await self._stream()
            except asyncio.CancelledError:
                raise
            except _Refused as e:
                self._lost(str(e))
                wait = REFUSED_RETRY_SECONDS
            except Exception as e:                               # the dashboard must keep running whatever the Twin does
                self._lost(f"{type(e).__name__}")
            self.connected = False
            await asyncio.sleep(wait)

    def _lost(self, why: str) -> None:
        if why != self.error:
            log.warning("Live feed: %s", why)
        self.connected, self.error = False, why

    async def _stream(self) -> None:
        timeout = httpx2.Timeout(5.0, read=READ_TIMEOUT_SECONDS)
        async with httpx2.AsyncClient(timeout=timeout, headers={"Authorization": f"Bearer {self.key}"}) as http:
            async with http.stream("GET", self.url) as response:
                if response.status_code in (401, 403):
                    raise _Refused(f"the Twin refused the dashboard's key (HTTP {response.status_code})")
                if response.status_code != 200:
                    raise _Refused(f"the Twin answered HTTP {response.status_code}")
                event, data = None, []
                async for line in response.aiter_lines():
                    if line == "":                                   # a blank line ends one event
                        if event and data:
                            self._handle(event, "\n".join(data))
                        event, data = None, []
                    elif line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())

    def _handle(self, event: str, text: str) -> None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return                                                   # one bad event must not stop the feed
        if not isinstance(payload, dict):
            return
        if event == "hello":
            self.connected, self.error = True, None
            self.run_id = payload.get("run_id")
        elif event == "readings":
            self.connected, self.error = True, None
            if payload.get("run_id") != self.run_id:                 # a new run: forget the old values
                self.latest.clear()
            self.run_id, self.tick, self.sim_time = payload.get("run_id"), payload.get("tick"), payload.get("time")
            readings = [r for r in payload.get("readings", []) if isinstance(r, dict) and "device_id" in r and "node_id" in r]
            self.count = len(readings)
            for r in readings:
                key = r["device_id"] + (f"/{r['channel']}" if r.get("channel") else "")
                self.latest[key] = {k: r.get(k) for k in ("device_id", "node_id", "sensor", "channel", "value", "unit", "tick")}
            self.last_event = time.monotonic()
            self.version += 1


class _Refused(Exception):
    pass
