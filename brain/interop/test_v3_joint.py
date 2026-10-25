"""Opt-in checks of exact v3 tags. Test planner, actual Guardian, actual Twin.

Positive action acceptance assertions remain ordinary failures when partners
refuse the workflow. No source edits, replacement scores or token conversion.
"""

import asyncio
import base64
import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager

import httpx
import pytest

from civis_brain.contracts import ReadingsBatch
from civis_brain.integration.guardian_v3 import APPROVAL_TOOL, SCORE_TOOL, GuardianV3Peer
from civis_brain.integration.runtime import build_runtime

from .test_partners import GKEY, GUARDIAN, KEY, OUT, SKEY, MCPPeer, prepare, save, wait_tick
from .test_v2_joint import capture_batches

API_KEY = "integration-guardian-http-only"
BRAIN_KEY = "integration-brain-guardian-v3"


@contextmanager
def actual_guardian(twin_url):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "PORT": str(port), "TWIN_BASE_URL": twin_url.removesuffix("/mcp"),
           "GUARDIAN_TWIN_BEARER_KEY": GKEY, "GUARDIAN_API_BEARER_KEY": API_KEY,
           "GUARDIAN_BRAIN_MCP_BEARER_KEY": BRAIN_KEY, "DEMO_MODE": "false"}
    env.pop("PYTHONPATH", None)
    with (OUT / f"guardian-v3-{port}.log").open("w") as log:
        process = subprocess.Popen([os.environ["CIVIS_TEST_GUARDIAN_PYTHON"], str(GUARDIAN / "src/run.py")],
            cwd=GUARDIAN, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                assert process.poll() is None, "Exact Guardian v3 startup failed; inspect local log"
                try:
                    if httpx.get(url + "/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                pytest.fail("Guardian v3 startup timed out")
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


async def ingest(url, batch):
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(url + "/api/integrations/twin/event",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"event": "readings", "data": batch})
        response.raise_for_status()
        return response.json()


async def test_v3_tools_and_native_ingestion(twin):
    _, twin_url = twin
    with actual_guardian(twin_url) as url:
        raw = MCPPeer(url + "/mcp", BRAIN_KEY, 10)
        assert {"describe_capabilities", "get_trust_verdict", "authorize_action"}.issubset(
            await raw.list_tool_names())
        adapter = GuardianV3Peer(raw)
        capability = await adapter.call_tool("get_capabilities", {})
        assert capability["thresholds"]["reading"] == .7
        client = MCPPeer(twin_url, KEY, 10)
        batch = await client.call_tool("get_readings", {})
        result = await ingest(url, batch)
        row = next(r for r in batch["readings"] if r["sensor"] == "congestion_index")
        verdict = await raw.call_tool("get_trust_verdict", {"reading_id": row["reading_id"], "fresh": True})
        save("v3-native-ingestion", {"ingestion": result, "verdict": verdict, "capability": capability})
        assert verdict["caused_by"] == row["reading_id"]


async def test_guardian_native_discovery_accepts_current_mcp(twin):
    _, twin_url = twin
    code = """
import json
try:
 from twin_discovery import discover_twin_sync
 result=discover_twin_sync(timeout_seconds=5)
 print(json.dumps({'ok':True,'keys':list(result)}))
except Exception as exc:
 import traceback
 print(json.dumps({'ok':False,'error':str(exc),'traceback':traceback.format_exc()}))
"""
    result = await asyncio.to_thread(subprocess.run,
        [os.environ["CIVIS_TEST_GUARDIAN_PYTHON"], "-c", code], cwd=GUARDIAN / "src",
        env={**os.environ, "TWIN_BASE_URL": twin_url.removesuffix("/mcp"),
             "GUARDIAN_TWIN_BEARER_KEY": GKEY}, capture_output=True, text=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    body = json.loads(result.stdout.strip().splitlines()[-1])
    save("v3-guardian-native-discovery", body)
    assert body["ok"], body


async def test_twin_accepts_signed_g1_wire_with_test_signer(twin):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from civis_brain.inputs.service import utc_time

    app, url = twin
    private = Ed25519PrivateKey.generate()
    app.state.settings.config.tokens.mode = "signed"
    app.state.settings.config.tokens.guardian_public_key = base64.b64encode(
        private.public_key().public_bytes_raw()).decode()
    peer = MCPPeer(url, KEY)
    clock = await peer.call_tool("get_clock", {})
    action = next(a for a in (await peer.call_tool("list_actions", {}))["actions"]
                  if a["action"] == "set_signal_plan")
    now = utc_time(clock["time"]).timestamp()
    params = {"plan": next(p for p in action["params"] if p["name"] == "plan")["choices"][0]}
    claims = {"v": 1, "kid": "test-only", "token_id": "g1-test", "iss": "guardian", "aud": "twin",
              "run_id": clock["run_id"], "iat": now, "exp": now + 60, "trust_score": .9,
              "action": action["action"], "targets": [action["target_nodes"][0]], "params": params,
              "reading_ids": ["test-only-reading"], "risk_level": "R1", "idempotency_key": "g1-test"}
    payload = base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    signing = "g1." + payload
    token = signing + "." + base64.urlsafe_b64encode(private.sign(signing.encode())).decode().rstrip("=")
    result = await peer.call_tool("actuate", {"action": action["action"], "targets": claims["targets"],
        "params": params, "token": token, "idempotency_key": "g1-test"})
    save("v3-g1-test-signer", {"signer": "local test key, not actual Guardian approval", "result": result})
    assert result["status"] == "committed", result


@pytest.mark.parametrize("sid", ["S01", "S02", "S03", "S04", "S05"])
async def test_v3_five_workflow_acceptance(twin, sid):
    app, twin_url = twin
    # prepare() returns a test Guardian too, deliberately discarded here.
    client, case, _, provider, _ = await prepare(twin_url, sid)
    if sid == "S01":
        actions = (await client.call_tool("list_actions", {}))["actions"]
        action = next(a for a in actions if a["action"] == "set_signal_plan")
        nodes = (await client.call_tool("list_nodes", {}))["nodes"]
        target = next(n["node_id"] for n in nodes if n["node_id"] in action["target_nodes"] and len(n["domains"]) == 1)
        row = next(r for r in (await client.call_tool("get_readings", {}))["readings"]
                   if r["sensor"] == "congestion_index" and r["node_id"] == target)
        from .test_partners import RecordedPlan
        plan = next(p for p in action["params"] if p["name"] == "plan")["choices"][0]
        provider = RecordedPlan("set_signal_plan", [target], {"plan": plan})
        fault = await MCPPeer(twin_url, SKEY).call_tool("run_scenario", {"name": "fake_reading",
            "params": {"device_id": row["device_id"], "value": 95, "delay_ticks": 1}})
        await wait_tick(client, fault["faults"][0]["start_tick"])
    public = os.environ["GUARDIAN_TOKEN_PUBLIC_KEY"]
    app.state.settings.config.tokens.mode = "signed"
    app.state.settings.config.tokens.guardian_public_key = public
    with actual_guardian(twin_url) as url:
        adapter = GuardianV3Peer(MCPPeer(url + "/mcp", BRAIN_KEY, 15))
        runtime = build_runtime(twin=client, guardian=adapter, provider=provider,
            policies={sid: case["policy"]}, features={"enabled_scenario_ids": [sid],
                "guardian_score_tool": SCORE_TOOL, "guardian_token_tool": APPROVAL_TOOL,
                "guardian_exact_idempotency": True, "guardian_contract_confirmed": True,
                "mock_integration_profile": True, "preview_tool": "preview_action",
                "max_evidence_age_seconds": 60, "peer_timeout_seconds": 20,
                "ai_max_calls_per_run": 10}, artifact_dir=OUT / "workflows" / sid)
        batches = await capture_batches(twin_url, max(1, case["policy"].get("persistence_ticks", 1)))
        results, ingestion = [], []
        for batch in batches:
            ingestion.append(await ingest(url, batch))
            results.append((await runtime.evaluate_tick(ReadingsBatch.model_validate(batch))).model_dump())
        save("v3-workflow-" + sid, {"results": results, "ingestion": ingestion,
            "planner": "recorded test planner", "guardian": "actual tagged v3",
            "twin": "actual tagged mock 3", "test_water_topology": sid == "S02"})
        decisions = results[-1]["decisions"]
        assert decisions, "No usable incident reached the shared pipeline"
        expected = "committed" if sid in {"S01", "S02", "S05"} else "alert"
        assert any(d["status"] == expected for d in decisions), decisions
        await runtime.close()


async def test_v3_guardian_scores_actual_availability(twin):
    _, twin_url = twin
    with actual_guardian(twin_url) as url:
        batch = await MCPPeer(twin_url, KEY).call_tool("get_readings", {})
        result = await ingest(url, batch)
        row = next(r for r in batch["readings"] if r["sensor"] == "units_free")
        peer = MCPPeer(url + "/mcp", BRAIN_KEY, 10)
        try:
            verdict = await peer.call_tool("get_trust_verdict", {"reading_id": row["reading_id"]})
        except Exception as exc:
            save("v3-availability", {"skipped": result["skipped"], "error_type": type(exc).__name__})
            pytest.fail("Guardian did not provide trust for actual units_free evidence")
        assert verdict["caused_by"] == row["reading_id"]


def test_v3_legacy_mutations_require_auth(twin):
    with actual_guardian(twin[1]) as url:
        result = httpx.post(url + "/quarantine_device/test-auth", timeout=10)
        save("v3-legacy-auth", {"status": result.status_code, "body": result.json()})
        assert result.status_code in {401, 403}


def test_v3_rollback_withdraws_previous_trust(twin):
    from .test_partner_acceptance import reading

    with actual_guardian(twin[1]) as url:
        with httpx.Client(base_url=url, timeout=15,
                          headers={"Authorization": f"Bearer {API_KEY}"}) as client:
            client.post("/api/reset").raise_for_status()
            row = reading()
            client.post("/ingest", json=row).raise_for_status()
            rollback = client.post("/rollback_reading", json={"sensor_id": row["sensor_id"],
                                                               "reading_id": row["reading_id"]})
            rollback.raise_for_status()
            verdict = client.get(f'/trust_verdict/{row["sensor_id"]}/{row["reading_id"]}')
            save("v3-rollback", {"rollback": rollback.json(), "status": verdict.status_code,
                                  "verdict": verdict.json()})
            assert verdict.status_code != 200 or verdict.json().get("trust_score", 0) == 0


def test_v3_caller_cannot_disable_signature_validation(twin):
    from .test_partner_acceptance import reading

    with actual_guardian(twin[1]) as url:
        with httpx.Client(base_url=url, timeout=15,
                          headers={"Authorization": f"Bearer {API_KEY}"}) as client:
            client.post("/api/reset").raise_for_status()
            row = {**reading(), "signature": "invalid", "require_signature": True}
            strict = client.post("/ingest", json=row)
            bypass = client.post("/ingest", json={**row, "require_signature": False})
            save("v3-signature", {"strict_status": strict.status_code,
                                    "disabled_status": bypass.status_code})
            assert strict.status_code == 401 and bypass.status_code == 401
