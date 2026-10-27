"""Shared helpers for the Twin team's two stand-ins (mock_brain.py and mock_guardian.py).

These stand-ins are made by the Twin team so the Twin can be shown ALONE (rule R1). They are NOT the Brain team's or
Guardian team's layers and know nothing about their real code. They only call the Twin, the way those layers would.

Where the Twin lives and which keys to use are settings, never hard-coded:
  address : --url, or the environment variable TWIN_URL, or `server` in config/twin.yaml (default http://127.0.0.1:8000)
  keys    : --key, or the environment variable TWIN_KEY_CITY_BRAIN / TWIN_KEY_GUARDIAN / TWIN_KEY_SCENARIO,
            or the same names in twin/.env (the file the Twin itself reads). Fake dev keys only.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx2
import yaml
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

TWIN_ROOT = Path(__file__).resolve().parents[1]


class MockError(Exception):
    """A clear message for a person at the terminal (a missing key, the Twin not running, a refused call)."""


def twin_url(cli_value: str | None = None) -> str:
    if cli_value:
        return cli_value.rstrip("/")
    if os.environ.get("TWIN_URL"):
        return os.environ["TWIN_URL"].rstrip("/")
    try:
        server = yaml.safe_load((TWIN_ROOT / "config" / "twin.yaml").read_text(encoding="utf-8"))["server"]
        return f"http://{server['host']}:{server['port']}"
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        return "http://127.0.0.1:8000"


def _dotenv_value(name: str) -> str | None:
    """Read one value from twin/.env (plain KEY=VALUE lines, # starts a comment). No other parsing."""
    path = TWIN_ROOT / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def key_for(who: str, cli_value: str | None = None) -> str:
    """`who` is city_brain, guardian or scenario. Raises MockError with the fix if no key can be found."""
    if cli_value:
        return cli_value
    name = f"TWIN_KEY_{who.upper()}"
    value = os.environ.get(name) or _dotenv_value(name)
    if not value:
        raise MockError(f"No key for {who}. Pass --key, set {name} in the environment, or put it in twin/.env "
                        f"(copy .env.example).")
    return value


class TwinClient:
    """One open MCP session to the Twin with one caller's key.

        async with TwinClient(url, key) as twin:
            clock = await twin.call("get_clock")
    """

    def __init__(self, url: str, key: str | None):
        self.url, self.key = url.rstrip("/"), key
        self._http = None
        self._client = None

    async def __aenter__(self) -> "TwinClient":
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        self._http = httpx2.AsyncClient(headers=headers)
        await self._http.__aenter__()
        self._client = Client(streamable_http_client(self.url + "/mcp", http_client=self._http))
        try:
            await self._client.__aenter__()
        except Exception as exc:
            await self._http.__aexit__(None, None, None)
            raise MockError(f"Could not reach the Twin at {self.url}. Is it running? ({type(exc).__name__})") from exc
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            await self._client.__aexit__(*exc)
        finally:
            await self._http.__aexit__(*exc)

    async def call(self, tool: str, args: dict | None = None) -> dict:
        """Call a Twin tool and return its answer as a dict. A failed call (wrong input, no access) raises MockError.
        A REFUSED action is not a failed call: it comes back as a normal answer with status "rejected"."""
        result = await self._client.call_tool(tool, args or {})
        if result.is_error:
            raise MockError(f"{tool} failed: {result.content[0].text if result.content else 'no message'}")
        return result.structured_content or {}


def default_parts_dir() -> Path:
    """Where the Twin writes its own part files: `logging.parts_dir` in config/twin.yaml, counted from the twin/ folder.
    (The Twin counts it from the folder you start it in. Start everything from twin/ and the two are the same place.)"""
    try:
        raw = yaml.safe_load((TWIN_ROOT / "config" / "twin.yaml").read_text(encoding="utf-8"))["logging"]["parts_dir"]
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        raw = "run-logs"
    path = Path(raw)
    return path if path.is_absolute() else TWIN_ROOT / path


class PartLog:
    """One stand-in's run log, in the shared format: <run_id>.<layer>.jsonl, one JSON object per line.

    Same fields as the Twin's own lines: run_id, event_id (guardian-000001), timestamp (simulated), tick, wall (real
    clock), layer, event_type, caused_by, data. Every event carries `stand_in: true` in its data, so nobody can mistake
    these for the real Brain's or the real Guardian's events (the dashboard shows a badge when it sees the mark).
    The Twin merges these files with its own when it merges a run (python -m twin.logmerge does the same by hand).
    """

    def __init__(self, layer: str, parts_dir: Path | str | None = None):
        if layer not in ("guardian", "brain"):
            raise MockError(f"A stand-in log is for 'guardian' or 'brain', not {layer!r}.")
        self.layer = layer
        self.dir = Path(parts_dir) if parts_dir else default_parts_dir()

    def write(self, stamp: dict, event_type: str, data: dict, caused_by: list[str] | None = None) -> str:
        """`stamp` is what get_clock answered: run_id, tick, time. Returns the new event_id."""
        path = self.dir / f"{stamp['run_id']}.{self.layer}.jsonl"
        self.dir.mkdir(parents=True, exist_ok=True)
        number = (sum(1 for _ in open(path, encoding="utf-8")) if path.exists() else 0) + 1
        event_id = f"{self.layer}-{number:06d}"
        line = {"run_id": stamp["run_id"], "event_id": event_id, "timestamp": stamp["time"], "tick": stamp["tick"],
                "wall": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "layer": self.layer, "event_type": event_type, "caused_by": caused_by or [],
                "data": {**data, "stand_in": True}}
        with open(path, "a", encoding="utf-8") as f:                  # one short line, flushed at once
            f.write(json.dumps(line, separators=(",", ":"), ensure_ascii=False) + "\n")
        return event_id
