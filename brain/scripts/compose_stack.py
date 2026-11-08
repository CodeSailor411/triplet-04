"""Run CIVIS with the reviewed Triplet 04 Compose base in an isolated checkout snapshot."""

import argparse
import hashlib
import os
import secrets
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAIN = ROOT / "brain"
# PR #35 includes current Guardian main and the current real-jam Twin runtime.
COMPOSE_BASE = "e00e6c3a45e665aa48c9523f11119abf7f127a02"
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
        git("fetch", "origin", "twin-docker-compose")
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
        project = "triplet04-civis-" + hashlib.sha256(os.fsencode(ROOT)).hexdigest()[:8]
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
        subprocess.run(prefix + command, cwd=stage, check=True)
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
