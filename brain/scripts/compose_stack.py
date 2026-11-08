"""Run CIVIS with the reviewed Triplet 04 Compose base in an isolated checkout snapshot."""

import argparse
import hashlib
import json
import os
import re
import secrets
import ssl
import subprocess
import sys
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
import asyncio, json, ssl, sys, urllib.request
from civis_brain.errors import BrainError
from civis_brain.integration.mcp_peer import MCPPeer
from civis_brain.preflight import check
from civis_brain.settings import load_settings

async def probe_verdict(guardian, sample, attempts):
    reading_id = sample["reading_id"]
    result = {**sample, "status": "unavailable"}
    for attempt in range(attempts):
        try:
            reply = await guardian.call_tool("get_trust_verdict", {"reading_id": reading_id})
            verdict = reply.get("result", reply)
            if isinstance(verdict, dict):
                score = verdict.get("trust_score")
                if verdict.get("caused_by") == reading_id and type(score) in (int, float) and 0 <= score <= 1:
                    return {**sample, "status": "scored", "trust_score": score}
                if verdict.get("status") == "pending" and verdict.get("reading_id") == reading_id:
                    result["error_code"] = "GUARDIAN_VERDICT_NOT_READY"
                else:
                    result["error_code"] = "VERDICT_REPLY_MISMATCH"
            else:
                result["error_code"] = "VERDICT_REPLY_MISMATCH"
        except BrainError as error:
            result["error_code"] = error.code
        if attempt + 1 < attempts:
            await asyncio.sleep(0.5)
    return result

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
    sample = {"run_id": batch["run_id"], "tick": batch["tick"],
              "reading_id": batch["readings"][0]["reading_id"]}
    live = await probe_verdict(guardian, sample, 6)
    result["guardian_live_lookup"] = live
    result["guardian_scored_live_reading"] = live["status"] == "scored"
    audited = json.loads(sys.argv[1])
    if (not result["guardian_scored_live_reading"] and audited
            and audited["run_id"] == sample["run_id"] and audited["tick"] <= sample["tick"]):
        result["guardian_audited_lookup"] = await probe_verdict(guardian, audited, 1)
    return result

if __name__ == "__main__":
    context = ssl.create_default_context(cafile="/run/civis-ca/brain.crt")
    with urllib.request.urlopen("https://127.0.0.1:8001/health", context=context, timeout=3) as response:
        health = json.load(response)
    result = asyncio.run(connection_checks())
    print(json.dumps({"feed": health["feed"], "event_log": health["event_log"], **result}, indent=2))
    raise SystemExit(0 if result["ready"] and result["guardian_scored_live_reading"]
                     and health["feed"]["state"] == "connected" and health["feed"]["evaluated"] > 0
                     and not health["event_log"]["error"] else 2)
"""
T2_CONTROL = """
import asyncio, json, sys
from mock_common import MockError, TwinClient, key_for

async def control_t2():
    resetting = sys.argv[1] == "reset"
    if not resetting:
        run_id, scored_tick = sys.argv[2], int(sys.argv[3])
        async with TwinClient("http://127.0.0.1:8000", key_for("city_brain")) as twin:
            clock = await twin.call("get_clock")
        if clock["run_id"] != run_id:
            raise MockError(f"Twin changed runs while waiting for Guardian in {run_id}")
        if not 0 <= clock["tick"] - scored_tick <= 5:
            raise MockError(f"Guardian is behind Twin in {run_id}. Run check before retrying T2.")
    async with TwinClient("http://127.0.0.1:8000", key_for("scenario")) as twin:
        if resetting:
            reset = await twin.call("run_scenario", {"name": "reset"})
            if reset.get("status") != "reset" or not reset.get("run_id"):
                raise MockError("Twin did not confirm the run reset")
            print(json.dumps(reset), flush=True)
            return
        jam = await twin.call("run_scenario", {
            "name": "real_jam",
            "params": {"node_id": "SH-05", "hold_ticks": 180},
        })
        if jam.get("status") != "started" or jam.get("run_id") != run_id:
            raise MockError(f"Twin did not confirm a jam in {run_id}")
        print(json.dumps(jam), flush=True)

try:
    asyncio.run(control_t2())
except MockError as error:
    raise SystemExit(str(error)) from None
"""
T2_WAIT_FOR_GUARDIAN = """
import json, os, sys, time
from pathlib import Path

run_id = sys.argv[1]
audit = Path(os.environ.get("GUARDIAN_AUDIT_DIR", "run-logs")) / f"{run_id}.guardian.jsonl"
try:
    offset = audit.stat().st_size
except FileNotFoundError:
    offset = 0
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    try:
        with audit.open("rb") as stream:
            stream.seek(offset)
            while line := stream.readline():
                if not line.endswith(b"\\n"):
                    break
                offset = stream.tell()
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(row, dict) and row.get("run_id") == run_id
                        and row.get("event_type") == "reading_evaluated"
                        and row.get("data", {}).get("sensor_id") == "SH-05.congestion_index"
                        and type(row.get("tick")) is int and type(row.get("trust_score")) in (int, float)
                        and 0 <= row["trust_score"] <= 1):
                    print(row["tick"])
                    raise SystemExit(0)
    except FileNotFoundError:
        pass
    time.sleep(0.25)
raise SystemExit(f"Guardian did not score a new SH-05 reading in {run_id} within 30 seconds. Jam was not started.")
"""


def start_t2(prefix, stage):
    control = prefix + ["exec", "-T", "-e", "PYTHONPATH=/app/twin/src:/app/twin/mocks",
                        "twin", "python", "-c", T2_CONTROL]
    reset = subprocess.run(control + ["reset"], cwd=stage, check=True, stdout=subprocess.PIPE, text=True)
    run_id = json.loads(reset.stdout)["run_id"]
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("Twin returned an invalid run ID")
    print(f"Twin reset to {run_id}. Reconnecting Guardian's feed before starting the jam.", file=sys.stderr)
    subprocess.run(prefix + ["restart", "--no-deps", "guardian-feed"], cwd=stage,
                   stdout=subprocess.DEVNULL, check=True)
    scored = subprocess.run(prefix + ["exec", "-T", "guardian", "python", "-c", T2_WAIT_FOR_GUARDIAN, run_id],
                            cwd=stage, check=True, stdout=subprocess.PIPE, text=True)
    subprocess.run(control + ["jam", run_id, str(int(scored.stdout))], cwd=stage, check=True)


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
        "Trinity dashboard": "http://127.0.0.1:8080/health",
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


def recent_events(path):
    """Read recent complete rows only, so checks stay quick on long runs."""
    try:
        with path.open("rb") as stream:
            start = max(0, stream.seek(0, os.SEEK_END) - 262144)
            stream.seek(start)
            if start:
                stream.readline()
            lines = stream.read().split(b"\n")[:-1]
    except FileNotFoundError:
        return
    except OSError as error:
        print(f"Could not read {path}: {error.strerror}", flush=True)
        return
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and type(row.get("tick")) is int:
            yield row


def latest_event_tick(path, kind):
    return next((row["tick"] for row in recent_events(path)
                 if row.get("event_type") == kind), None)


def print_timeline_progress(stage, clock):
    run_id = clock.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        return
    parts = stage / "brain" / "run-logs"
    native = stage / "guardian" / "run-logs" / f"{run_id}.guardian.jsonl"
    scored = [row for row in recent_events(native)
              if row.get("run_id") == run_id and row.get("event_type") == "reading_evaluated"
              and type(row.get("trust_score")) in (int, float)]
    scored_tick = scored[0]["tick"] if scored else None
    twin_tick = clock.get("tick")
    print("Timeline ticks (latest written per file): " + json.dumps({
        "run_id": run_id,
        "twin_clock": twin_tick,
        "twin_feed_on_dashboard": latest_event_tick(parts / f"{run_id}.twin.jsonl", "reading"),
        "guardian_scored": scored_tick,
        "guardian_lag_ticks": twin_tick - scored_tick if type(twin_tick) is int and scored else None,
        "guardian_on_dashboard": latest_event_tick(parts / f"{run_id}.guardian.jsonl", "verdict"),
    }), flush=True)
    return next(({key: row[key] for key in ("run_id", "tick", "reading_id")} for row in scored
                 if isinstance(row.get("reading_id"), str)
                 and row["reading_id"].endswith(".congestion_index")), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "up", "check", "t2", "ps", "logs", "down", "config"),
                        help="t2 resets the simulation and starts a sustained SH-05 traffic jam")
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
        # Twin run IDs can repeat in a fresh checkout snapshot.
        os.environ["TRIPLET_GUARDIAN_AUDIT_VOLUME"] = f"{project}-guardian-audit-{stage.name}"
        prefix = ["docker", "compose", "--project-name", project, "--env-file", str(env_file),
                  "-f", "docker-compose.yml", "-f", "brain/compose.override.yml"]
        if args.command == "t2":
            start_t2(prefix, stage)
            return
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
            sample = print_timeline_progress(stage, clock)
            command.append(json.dumps(sample))
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
