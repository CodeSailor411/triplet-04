"""Opt-in localhost checks against untouched partner source snapshots.

Control runs explicitly use a test Guardian. Real Guardian checks never mint tokens.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import httpx2
import pytest
from civis_mock_peers.http import peer_app, serve
from civis_mock_peers.peers import FixtureGuardian
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from civis_brain.app import create_app as brain_app
from civis_brain.contracts import Plan, ReadingsBatch
from civis_brain.integration.feed import TwinFeed
from civis_brain.integration.mcp_peer import MCPPeer
from civis_brain.integration.runtime import build_runtime
from civis_brain.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
TWIN = Path(os.environ["CIVIS_TEST_TWIN_ROOT"]).resolve()
GUARDIAN = Path(os.environ["CIVIS_TEST_GUARDIAN_ROOT"]).resolve()
OUT = ROOT / ".artifacts" / "interop-oct19"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(TWIN / "src"))
from twin.app import create_app as twin_app  # noqa: E402
from twin.settings import Secrets, load_config  # noqa: E402
from twin.settings import Settings as TwinSettings  # noqa: E402

KEY = "integration-test-brain-only"
GKEY = "integration-test-guardian-only"
SKEY = "integration-test-scenario-only"
DOMAINS = {"S01": "traffic", "S02": "water", "S03": "power", "S04": "air_quality", "S05": "emergency"}


def save(name, data):
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.fixture
def twin():
    config = load_config(TWIN / "config/twin.yaml")
    config.logging.enabled = False
    config.clock.autorun = True
    config.clock.speed = 1
    assert config.clock.tick_seconds == 1
    app = twin_app(TwinSettings(config=config, secrets=Secrets(
        _env_file=None, city_brain=KEY, guardian=GKEY, scenario=SKEY)))
    with serve(app) as url:
        yield app, url


@pytest.fixture(scope="session")
def guardian_url():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env["PORT"] = str(port)
    env.pop("PYTHONPATH", None)
    with (OUT / "guardian-server.log").open("w") as log:
        process = subprocess.Popen(
            [os.environ["CIVIS_TEST_GUARDIAN_PYTHON"], str(GUARDIAN / "backend/run.py")],
            cwd=GUARDIAN, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                assert process.poll() is None, "Guardian exited; inspect local server log"
                try:
                    response = httpx.get(url + "/health", timeout=2)
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else:
                pytest.fail("Guardian startup failed")
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


async def inventory(url, key=""):
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=5) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            tools = await client.list_tools()
            return {"protocol": client.protocol_version, "tools": [t.name for t in tools.tools]}


async def wait_tick(client, tick):
    async with asyncio.timeout(12):
        while True:
            batch = await client.call_tool("get_readings", {})
            if batch["tick"] >= tick:
                return batch
            await asyncio.sleep(.1)


class RecordedPlan:
    """Explicit test planner; no claim of a live Gemini call."""
    def __init__(self, action=None, targets=None, params=None, delay=0):
        self.action, self.targets, self.params, self.delay = action, targets, params, delay

    async def generate(self, context):
        await asyncio.sleep(self.delay)
        manifest = next(a for a in context.actions if a.action == self.action)
        return Plan.model_validate({"proposals": [{
            "action": self.action, "targets": self.targets, "params": self.params,
            "risk": manifest.risk, "preview_required": manifest.preview_required,
            "source_reading_ids": [r.reading_id for r in context.evidence_readings],
            "reason": "Controlled integration test plan"}], "alerts": []})


async def prepare(url, sid, *, denied=False, delay=0):
    client = MCPPeer(url, KEY)
    scenario = MCPPeer(url, SKEY)
    case = json.loads((ROOT / f"mocks/cases/{DOMAINS[sid]}/base_case.json").read_text())
    batch = await client.call_tool("get_readings", {})
    actions = (await client.call_tool("list_actions", {}))["actions"]
    nodes = (await client.call_tool("list_nodes", {}))["nodes"]
    action_name = {"S02": "set_valve_position", "S05": "dispatch"}.get(sid)
    provider = RecordedPlan()
    faults = []
    if sid in {"S02", "S05"}:
        manifest = next(a for a in actions if a["action"] == action_name)
        target = next(n["node_id"] for n in nodes if n["node_id"] in manifest["target_nodes"] and len(n["domains"]) == 1)
        sensor = "water_level" if sid == "S02" else "emergency_calls"
        row = next(r for r in batch["readings"] if r["sensor"] == sensor and (sid != "S02" or r["node_id"] == target)
                   and (sid == "S02" or r["channel"] == "medical"))
        params = {"position": 30.0} if sid == "S02" else {"unit_type": "ambulance", "destination": row["node_id"], "units": 1}
        provider = RecordedPlan(action_name, [target], params, delay)
        if sid == "S02":
            # Test topology only, not an inferred hydraulic safety promise.
            case["policy"]["safe_valve_choices"] = [{"incident_node_id": target, "targets": [target], "params": params}]
        faults.append({"device_id": row["device_id"], "channel": row["channel"], "value": 180 if sid == "S02" else 2})
    elif sid == "S04":
        row = next(r for r in batch["readings"] if r["sensor"] == "pm25")
        faults.append({"device_id": row["device_id"], "value": 120})
    for fault in faults:
        started = await scenario.call_tool("run_scenario", {"name": "fake_reading", "params": {**fault, "delay_ticks": 1}})
        batch = await wait_tick(client, started["faults"][0]["start_tick"])
    case["guardian"]["approve"] = not denied
    guardian = FixtureGuardian(case)
    return client, case, guardian, provider, batch


def runtime_for(client, case, guardian, provider, *, real_guardian=False):
    return build_runtime(twin=client, guardian=guardian, provider=provider,
        policies={case["scenario_id"]: case["policy"]},
        features={"enabled_scenario_ids": [case["scenario_id"]], "mock_integration_profile": True,
                  "guardian_contract_confirmed": not real_guardian,
                  "guardian_score_tool": "fixture_score", "guardian_token_tool": "fixture_approve",
                  "preview_tool": "preview_action", "ai_max_calls_per_run": 20,
                  "peer_timeout_seconds": 3, "max_evidence_age_seconds": 10},
        artifact_dir=OUT / ("real-guardian" if real_guardian else "test-guardian") / case["scenario_id"])


@pytest.mark.parametrize("sid", list(DOMAINS))
async def test_five_workflows_real_twin_test_guardian(twin, sid):
    app, url = twin
    client, case, guardian, provider, batch = await prepare(url, sid)
    with serve(peer_app(guardian, GKEY)) as g_url:
        runtime = runtime_for(client, case, MCPPeer(g_url, GKEY), provider)
        with serve(brain_app(Settings(_env_file=None), runtime)) as b_url:
            brain = MCPPeer(b_url, "dev-scenario-to-brain")
            for _ in range(case["policy"].get("persistence_ticks", 1)):
                result = await brain.call_tool("evaluate_tick", {"batch": batch})
                batch = await wait_tick(client, batch["tick"] + 1)
    statuses = [d["status"] for d in result["decisions"]]
    save(f"{sid}-real-twin-test-guardian", {"result": result, "tick": app.state.sim.tick,
                                         "authorization": "TEST GUARDIAN", "planner": "recorded", "live_clock": True})
    assert statuses and set(statuses) == {"committed" if sid in {"S02", "S05"} else "alert"}, result
    if sid == "S01":
        assert "congestion_index unavailable" in result["decisions"][0]["reason"]
        assert not app.state.book.state
    elif sid in {"S03", "S04"}:
        assert not app.state.book.state
    else:
        assert len(app.state.book.state) == 1


async def test_real_twin_clock_advances_during_planning(twin):
    app, url = twin
    client, case, guardian, provider, batch = await prepare(url, "S05", delay=2)
    runtime = runtime_for(client, case, guardian, provider)
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(batch))
    assert result.decisions[0].status == "committed", result
    approval = next(c for c in guardian.calls if c["name"] == "fixture_approve")
    assert approval["arguments"]["tick"] > batch["tick"]
    save("running-clock", {"input_tick": batch["tick"], "authorization_tick": approval["arguments"]["tick"],
                           "result": result.model_dump(), "authorization": "TEST GUARDIAN"})


async def test_actual_sse_drives_brain_without_manual_evaluate(twin):
    _, url = twin
    client, case, guardian, provider, _ = await prepare(url, "S04")
    runtime = runtime_for(client, case, guardian, provider)
    feed = TwinFeed(runtime, url.removesuffix("/mcp") + "/events", KEY)
    feed.start()
    try:
        async with asyncio.timeout(12):
            while not any(d.status == "alert" for d in runtime.decisions.values()):
                await asyncio.sleep(.1)
        assert feed.status["received"] >= 2 and feed.status["evaluated"] >= 2
        save("sse-brain", feed.status)
    finally:
        await feed.close()


async def test_actual_sse_continues_during_medical_planning(twin):
    app, url = twin
    client, case, guardian, provider, _ = await prepare(url, "S05", delay=2)
    runtime = runtime_for(client, case, guardian, provider)
    feed = TwinFeed(runtime, url.removesuffix("/mcp") + "/events", KEY)
    feed.start()
    try:
        async with asyncio.timeout(15):
            while not any(d.status == "committed" for d in runtime.decisions.values()):
                await asyncio.sleep(.1)
        assert feed.status["received"] > feed.status["evaluated"]
        assert len(app.state.book.state) == 1
        save("sse-during-medical-planning", {**feed.status, "authorization": "TEST GUARDIAN"})
    finally:
        await feed.close()


async def test_real_guardian_has_no_authorization_tool(guardian_url):
    found = await inventory(guardian_url + "/mcp")
    save("guardian-inventory", found)
    assert found["protocol"] == "2026-07-28"
    assert set(found["tools"]) == {"describe_capabilities", "evaluate_reading_advisory"}


async def test_real_three_layer_attempt_blocks_without_token(twin, guardian_url):
    app, url = twin
    client, case, _, provider, batch = await prepare(url, "S05")
    runtime = runtime_for(client, case, MCPPeer(guardian_url + "/mcp", GKEY), provider, real_guardian=True)
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(batch))
    assert result.decisions[0].peer_code == "GUARDIAN_CONTRACT_UNCONFIRMED"
    assert not app.state.book.state
    save("three-real-layers-blocker", {"result": result.model_dump(), "actuation_effects": 0,
                                      "acceptance": "BLOCKED: real Guardian cannot authorize"})


async def test_real_guardian_rejects_native_reading(twin, guardian_url):
    _, url = twin
    batch = await MCPPeer(url, KEY).call_tool("get_readings", {})
    row = next(r for r in batch["readings"] if r["sensor"] == "water_level")
    async with httpx.AsyncClient() as client:
        response = await client.post(guardian_url + "/ingest", json=row)
    save("guardian-native-reading", {"status": response.status_code, "response": response.json()})
    assert response.status_code == 422


async def test_guardian_denial_and_twin_containment_prevent_effects(twin):
    app, url = twin
    client, case, guardian, provider, batch = await prepare(url, "S05", denied=True)
    runtime = runtime_for(client, case, guardian, provider)
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(batch))
    assert result.decisions[0].peer_code == "GUARDIAN_DENIED" and not app.state.book.state
    guardian.case["guardian"]["approve"] = True
    target = provider.targets[0]
    device = next(r["device_id"] for r in batch["readings"] if r["node_id"] == target)
    reply = await MCPPeer(url, GKEY).call_tool("quarantine_device", {"device_ids": [device]})
    assert reply["status"] == "applied"
    batch = await wait_tick(client, batch["tick"] + 1)
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(batch))
    assert not app.state.book.state
    assert all(d.status != "committed" for d in result.decisions)
