"""Configurable Twin SSE and MCP clients; transport is kept outside policy/scoring."""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp.client.session import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


class TwinConnectionError(RuntimeError):
    pass


def twin_config() -> dict[str, Any]:
    base = os.environ.get("TWIN_BASE_URL", "").rstrip("/")
    key = os.environ.get("GUARDIAN_TWIN_BEARER_KEY", "")
    if not base:
        raise TwinConnectionError("TWIN_BASE_URL is not configured")
    if not key:
        raise TwinConnectionError("GUARDIAN_TWIN_BEARER_KEY is not configured")
    timeout = float(os.environ.get("TWIN_TIMEOUT_SECONDS", "15"))
    max_retries = int(os.environ.get("TWIN_MAX_RETRIES", "3"))
    retry_base = float(os.environ.get("TWIN_RETRY_BASE_SECONDS", "0.5"))
    if not 0 < timeout <= 120 or not 0 <= max_retries <= 10 or not 0 <= retry_base <= 10:
        raise TwinConnectionError("Twin timeout must be (0,120], retries [0,10], and retry base [0,10]")
    return {"base_url": base, "bearer_key": key, "timeout": timeout,
            "max_retries": max_retries, "retry_base_seconds": retry_base}


def normalize_twin_reading(item: dict[str, Any]) -> dict[str, Any]:
    """Map documented Twin common fields to current Guardian schema when possible."""
    if not isinstance(item, dict):
        raise ValueError("Twin reading must be a JSON object")
    required = {"run_id", "reading_id", "device_id", "timestamp", "tick", "sensor", "value", "unit", "lat", "lon"}
    missing = required - item.keys()
    if missing:
        raise ValueError(f"Twin reading missing fields: {', '.join(sorted(missing))}")
    for key in ("run_id", "reading_id", "device_id", "sensor", "unit"):
        if not isinstance(item[key], str) or not item[key]:
            raise ValueError(f"Twin {key} must be a non-empty string")
    sensor_type = {
        "congestion_index": "traffic_cam", "water_level": "water_level",
        "load_kw": "power_load", "pm25": "air_quality", "emergency_calls": "emergency_call",
    }.get(item["sensor"])
    if sensor_type is None:
        raise ValueError(f"Twin sensor {item['sensor']!r} has no Guardian mapping")
    timestamp = item["timestamp"]
    if isinstance(timestamp, str):
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("Twin timestamp must include a timezone")
        timestamp = parsed.timestamp()
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ValueError("Twin timestamp must be RFC 3339 or numeric epoch seconds")
    if not math.isfinite(timestamp) or timestamp <= 0:
        raise ValueError("Twin timestamp must be finite and positive")
    value = item["value"]
    if value is None:
        raise ValueError("Twin null sensor value is not scoreable")
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("Twin value must be numeric")
    if not math.isfinite(value):
        raise ValueError("Twin value must be finite")
    allowed_units = {
        "traffic_cam": {"%", "percent"},
        "water_level": {"cm", "centimeter", "centimeters", "m", "meter", "meters"},
        "power_load": {"kW"}, "air_quality": {"ug/m3", "µg/m³"},
        "emergency_call": {"calls_per_min", "calls/min"},
    }
    if item["unit"] not in allowed_units[sensor_type]:
        raise ValueError(f"Twin unit {item['unit']!r} is not valid for {sensor_type}")
    if sensor_type == "traffic_cam" and item["unit"] not in {"%", "percent"}:
        raise ValueError("congestion_index must use percent units")
    if sensor_type == "air_quality" and item["unit"] not in {"ug/m3", "µg/m³"}:
        raise ValueError("Guardian needs PM2.5 in ug/m3; AQI cannot be converted losslessly")
    try:
        if any(isinstance(item[k], bool) or not isinstance(item[k], (int, float)) for k in ("lat", "lon")):
            raise ValueError("Twin coordinates must be numeric")
        if isinstance(item["tick"], bool) or not isinstance(item["tick"], int):
            raise ValueError("Twin tick must be an integer")
        lat, lon, tick = float(item["lat"]), float(item["lon"]), item["tick"]
    except (TypeError, ValueError) as exc:
        raise ValueError("Twin lat, lon, and tick must be numeric") from exc
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or tick < 0:
        raise ValueError("Twin coordinates or tick are out of range")
    return {
        "reading_id": item["reading_id"], "sensor_id": item["device_id"],
        "sensor_type": sensor_type, "value": float(value), "unit": item["unit"],
        "timestamp": float(timestamp), "location": {"lat": lat, "lng": lon},
        "sequence_number": tick, "require_signature": False,
    }


class TwinSSEAdapter:
    def __init__(self, *, base_url: str, bearer_key: str, timeout: float = 15,
                 max_retries: int = 3, retry_base_seconds: float = .5):
        if not base_url or not bearer_key:
            raise ValueError("Twin URL and Guardian's Twin Bearer key are required")
        self.url = base_url.rstrip("/") + "/events"
        self.bearer_key, self.timeout = bearer_key, timeout
        self.max_retries, self.retry_base_seconds = max_retries, retry_base_seconds

    @classmethod
    def from_env(cls):
        cfg = twin_config()
        return cls(base_url=cfg["base_url"], bearer_key=cfg["bearer_key"], timeout=cfg["timeout"],
                   max_retries=cfg["max_retries"], retry_base_seconds=cfg["retry_base_seconds"])

    async def _read_event(self, response) -> dict[str, Any] | None:
        def read_block():
            lines = []
            while True:
                line = response.readline()
                if not line:
                    if not lines:
                        return None
                    break
                if line in (b"\n", b"\r\n"):
                    break
                lines.append(line.decode("utf-8").rstrip("\r\n"))
            return lines
        lines = await asyncio.to_thread(read_block)
        if lines is None:
            return None
        event = "message"
        data = []
        for line in lines:
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if not data:
            return {"event": event, "data": None}
        try:
            payload = json.loads("\n".join(data))
        except json.JSONDecodeError as exc:
            raise TwinConnectionError("Twin SSE sent malformed JSON") from exc
        if not isinstance(payload, dict):
            raise TwinConnectionError("Twin SSE event data must be a JSON object")
        return {"event": event, "data": payload}

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        attempt = 0
        while True:
            response = None
            try:
                req = Request(self.url, headers={"Authorization": f"Bearer {self.bearer_key}", "Accept": "text/event-stream"})
                response = await asyncio.to_thread(urlopen, req, timeout=self.timeout)
                if "text/event-stream" not in response.headers.get("Content-Type", ""):
                    raise TwinConnectionError("Twin /events did not return text/event-stream")
                while True:
                    event = await self._read_event(response)
                    if event is None:
                        raise TwinConnectionError("Twin SSE connection closed")
                    attempt = 0
                    yield event
            except asyncio.CancelledError:
                raise
            except (HTTPError, URLError, TimeoutError, OSError, TwinConnectionError) as exc:
                if isinstance(exc, HTTPError) and exc.code in (401, 403):
                    raise TwinConnectionError(f"Twin rejected Guardian credentials (HTTP {exc.code})") from exc
                if attempt >= self.max_retries:
                    raise TwinConnectionError(f"Twin SSE failed after {attempt + 1} connection attempts: {type(exc).__name__}: {exc}") from exc
                delay = min(self.retry_base_seconds * (2 ** attempt), 8.0)
                attempt += 1
                await asyncio.sleep(delay)
            finally:
                if response is not None:
                    await asyncio.to_thread(response.close)


@asynccontextmanager
async def twin_mcp_session(*, base_url: str, bearer_key: str, timeout: float = 15):
    """Open an MCP 2.x session with Twin's own Guardian-scoped credential."""
    url = base_url.rstrip("/") + "/mcp"
    from mcp.client.streamable_http import httpx2
    client = create_mcp_http_client(headers={"Authorization": f"Bearer {bearer_key}"},
                                    timeout=httpx2.Timeout(timeout))
    try:
        async with streamable_http_client(url, http_client=client) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream, read_timeout_seconds=timeout) as session:
                await session.initialize()
                yield session
    finally:
        await client.aclose()
