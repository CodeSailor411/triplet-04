"""Run CIVIS with the reviewed Triplet 04 Compose base in an isolated checkout snapshot."""

import argparse
import hashlib
import json
import os
import re
import secrets
import ssl
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[2]
BRAIN = ROOT / "brain"
# PR #35 includes the Twin and Guardian MCP hostname allowlists and current Guardian logs.
COMPOSE_BASE = "a374e9d5fce2d63739ee1b00a361b744f011262a"
KEYS = (
    "TWIN_KEY_CITY_BRAIN", "TWIN_KEY_GUARDIAN", "TWIN_KEY_SCENARIO",
    "GUARDIAN_API_BEARER_KEY", "GUARDIAN_BRAIN_MCP_BEARER_KEY",
    "BRAIN_TWIN_CALLER_KEY", "BRAIN_GUARDIAN_CALLER_KEY", "BRAIN_SCENARIO_KEY",
)
CHECK = """
import asyncio, json, ssl, urllib.request
from civis_brain.errors import BrainError
from civis_brain.integration.mcp_peer import MCPPeer
from civis_brain.preflight import check
from civis_brain.settings import load_settings

async def connection_checks():
    settings = load_settings()
    result = await check(settings)
    result["guardian_scored_live_reading"] = False
    if not result["ready"]:
        return result
    twin = MCPPeer(settings.twin_mcp_url, settings.twin_brain_key, settings.peer_timeout_seconds)
    guardian = MCPPeer(settings.guardian_mcp_url, settings.guardian_brain_key, settings.peer_timeout_seconds)
    batch = await twin.call_tool("get_readings", {"domain": "traffic", "sensor": "congestion_index"})
    if not batch["readings"]:
        return result
    reading_id = batch["readings"][0]["reading_id"]
    for _ in range(6):
        try:
            reply = await guardian.call_tool("get_trust_verdict", {"reading_id": reading_id})
            verdict = reply.get("result", reply)
            if verdict.get("caused_by") == reading_id and type(verdict.get("trust_score")) in (int, float):
                result["guardian_scored_live_reading"] = True
                break
        except BrainError:
            pass
        await asyncio.sleep(0.5)
    return result

context = ssl.create_default_context(cafile="/run/civis-ca/brain.crt")
with urllib.request.urlopen("https://127.0.0.1:8001/health", context=context, timeout=3) as response:
    health = json.load(response)
result = asyncio.run(connection_checks())
print(json.dumps({"feed": health["feed"], "event_log": health["event_log"], **result}, indent=2))
raise SystemExit(0 if result["ready"] and result["guardian_scored_live_reading"]
                 and health["feed"]["state"] == "connected" and health["feed"]["evaluated"] > 0
                 and not health["event_log"]["error"] else 2)
"""


def git(*args, **kwargs):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, **kwargs)


def init_env(path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("# Private local Compose settings. Never commit or share this file.\n")
        for name in KEYS:
            stream.write(f"{name}={secrets.token_urlsafe(32)}\n")
        stream.write("GEMINI_API_KEY=\n")


def export(ref, destination, archive, *paths):
    git("archive", "--format=tar", f"--output={archive}", ref, *paths)
    with tarfile.open(archive) as stream:
        stream.extractall(destination, filter="data")


def prepare_stack():
    head = git("rev-parse", "HEAD", capture_output=True, text=True).stdout.strip()
    parent = BRAIN / ".artifacts" / "compose"
    stage = parent / f"{head[:12]}-{COMPOSE_BASE[:12]}"
    if stage.is_dir():
        return stage
    try:
        git("cat-file", "-e", f"{COMPOSE_BASE}^{{commit}}", capture_output=True)
    except subprocess.CalledProcessError:
        git("fetch", "--no-tags", "origin", COMPOSE_BASE)
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as temporary:
        temporary = Path(temporary)
        snapshot, archive = temporary / "stack", temporary / "source.tar"
        snapshot.mkdir()
        export(COMPOSE_BASE, snapshot, archive, "docker-compose.yml", "twin", "guardian", "scenarios")
        export(head, snapshot, archive, "brain")
        if not (snapshot / "brain" / "compose.override.yml").is_file():
            raise ValueError("Check out a CIVIS commit that includes Compose support")
        snapshot.rename(stage)
    return stage


def check_published_ports(prefix, stage):
    public_cert = subprocess.run(
        prefix + ["exec", "-T", "brain", "cat", "/run/civis-ca/brain.crt"],
        cwd=stage, capture_output=True, text=True, check=True,
    ).stdout
    trust = ssl.create_default_context(cadata=public_cert)
    endpoints = {
        "Trinity Twin": "http://127.0.0.1:8000/health",
        "9antra Guardian": "http://127.0.0.1:5000/health",
        "CIVIS Brain": "https://127.0.0.1:8001/health",
        "Trinity dashboard": "http://127.0.0.1:8080/",
    }
    failed = False
    twin_clock = {}
    for name, url in endpoints.items():
        try:
            with urllib.request.urlopen(url, context=trust, timeout=5) as response:
                print(f"{name} {url} -> HTTP {response.status}", flush=True)
                if name == "Trinity Twin":
                    twin_clock = json.load(response)
        except (URLError, TimeoutError) as error:
            print(f"{name} {url} -> {error}", flush=True)
            failed = True
    return twin_clock, failed


def latest_event_tick(path, kind, score_field=None):
    """Read recent complete rows only, so checks stay quick on long runs."""
    try:
        with path.open("rb") as stream:
            start = max(0, stream.seek(0, os.SEEK_END) - 262144)
            stream.seek(start)
            if start:
                stream.readline()
            lines = stream.read().split(b"\n")[:-1]
    except FileNotFoundError:
        return None
    except OSError as error:
        print(f"Could not read {path}: {error.strerror}", flush=True)
        return None
    for line in reversed(lines):
        try:
            row = json.loads(line)
            if row.get("event_type") != kind or type(row.get("tick")) is not int:
                continue
            if score_field and type(row.get(score_field)) not in (int, float):
                continue
            return row["tick"]
        except (AttributeError, ValueError):
            continue
    return None


def print_timeline_progress(stage, clock):
    run_id = clock.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        return
    parts = stage / "brain" / "run-logs"
    native = stage / "guardian" / "run-logs" / f"{run_id}.guardian.jsonl"
    print("Timeline ticks (latest written per file): " + json.dumps({
        "run_id": run_id,
        "twin_clock": clock.get("tick"),
        "twin_feed_on_dashboard": latest_event_tick(parts / f"{run_id}.twin.jsonl", "reading"),
        "guardian_scored": latest_event_tick(native, "reading_evaluated", "trust_score"),
        "guardian_on_dashboard": latest_event_tick(parts / f"{run_id}.guardian.jsonl", "verdict"),
    }), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "up", "check", "ps", "logs", "down", "config"))
    args = parser.parse_args()
    env_file = BRAIN / ".env.compose"
    if args.command == "init":
        if not env_file.exists():
            init_env(env_file)
        print(f"Set GEMINI_API_KEY in {env_file}; the other keys are already configured.")
        return
    if not env_file.is_file():
        parser.error("Run init, then set GEMINI_API_KEY in brain/.env.compose")
    try:
        stage = prepare_stack()
        project = "triplet04-" + hashlib.sha256(os.fsencode(ROOT)).hexdigest()[:8]
        prefix = ["docker", "compose", "--project-name", project, "--env-file", str(env_file),
                  "-f", "docker-compose.yml", "-f", "brain/compose.override.yml"]
        command = {
            "up": ["up", "--build", "-d", "--wait"],
            "check": ["exec", "-T", "brain", "python", "-c", CHECK],
            "ps": ["ps"],
            "logs": ["logs", "--tail", "60"],
            "down": ["down"],
            "config": ["config", "--quiet"],
        }[args.command]
        port_failure = False
        if args.command == "check":
            clock, port_failure = check_published_ports(prefix, stage)
            print_timeline_progress(stage, clock)
        subprocess.run(prefix + command, cwd=stage, check=True)
        if port_failure:
            raise SystemExit(2)
        if args.command == "up":
            print("Dashboard: http://127.0.0.1:8080")
            print(f"Run logs and scenario scripts: {stage}")
            print("Run check before starting a live scenario.")
    except FileNotFoundError as error:
        parser.exit(2, f"{error.filename} was not found. Install Docker Desktop and Git.\n")
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None
    except ValueError as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
