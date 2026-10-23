"""Actual tagged peers, with explicit Guardian packaging workaround.

Recorded planning isolates transport/contracts from paid/external AI. No fake
Guardian or token translation is used. Green blocker checks are not joint action acceptance.
"""

import asyncio
import base64
import json
import os
import subprocess

import httpx
import pytest
from civis_mock_peers.http import serve
from cryptography.hazmat.primitives import serialization

from civis_brain.app import create_app
from civis_brain.contracts import ReadingsBatch
from civis_brain.errors import BrainError
from civis_brain.integration.guardian_http import APPROVAL_TOOL, SCORE_TOOL, GuardianHTTPPeer
from civis_brain.integration.runtime import build_runtime
from civis_brain.settings import Settings

from .test_partners import GKEY, GUARDIAN, KEY, OUT, MCPPeer, prepare, save

API_KEY = "integration-guardian-http-only"


async def post_batch(url, batch):
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(url + "/api/integrations/twin/event",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"event": "readings", "data": batch})
        response.raise_for_status()
        return response.json()


async def capture_batches(url, count):
    batches, event, data = [], "", []
    async with httpx.AsyncClient(timeout=15) as client:
        async with client.stream("GET", url.removesuffix("/mcp") + "/events",
                                 headers={"Authorization": f"Bearer {KEY}"}) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
                elif not line:
                    if event == "readings" and data:
                        batches.append(json.loads("\n".join(data)))
                        if len(batches) == count:
                            return batches
                    event, data = "", []
    raise AssertionError("SSE closed before requested observations")


def actual_guardian(url):
    policy = json.loads((GUARDIAN / "src/guardian_policy.json").read_text())
    return GuardianHTTPPeer(url, API_KEY, policy, timeout_seconds=10, allow_provisional=True)


@pytest.mark.parametrize("sid", ["S01", "S02", "S03", "S04", "S05"])
async def test_five_scenarios_actual_guardian_and_twin(twin, guardian_url, sid):
    app, url = twin
    httpx.post(guardian_url + "/api/reset", timeout=10).raise_for_status()
    client, case, _, provider, _ = await prepare(url, sid)
    batches = await capture_batches(url, case["policy"].get("persistence_ticks", 1))
    if len(batches) == 2:
        assert batches[1]["tick"] == batches[0]["tick"] + 1
    runtime = build_runtime(twin=client, guardian=actual_guardian(guardian_url), provider=provider,
        policies={sid: case["policy"]}, features={"enabled_scenario_ids": [sid],
            "mock_integration_profile": True, "guardian_contract_confirmed": True,
            "guardian_score_tool": SCORE_TOOL, "guardian_token_tool": APPROVAL_TOOL,
            "preview_tool": "preview_action", "peer_timeout_seconds": 15,
            "max_evidence_age_seconds": 60, "ai_max_calls_per_run": 10},
        artifact_dir=OUT / "actual-three-processes" / sid)
    summaries = []
    with serve(create_app(Settings(_env_file=None), runtime)) as brain_url:
        brain = MCPPeer(brain_url, "dev-scenario-to-brain", 20)
        for batch in batches:
            scored = await post_batch(guardian_url, batch)
            summaries.append({"tick": batch["tick"], "processed": scored["processed"],
                "skipped": scored["skipped"],
                "security_rejections": [{"reading_id": r["reading_id"],
                    "reason": r["evaluation"].get("rejection_reason")}
                    for r in scored["results"] if r["evaluation"].get("guardian") is None]})
            result = await brain.call_tool("evaluate_tick", {"batch": batch})
    save("joint-" + sid, {"scenario": sid, "guardian": "ACTUAL tagged v2 in diagnostic layout",
        "planner": "recorded control, not Gemini", "input": "actual Twin SSE; reported fault values",
        "result": result, "guardian_ingestion": summaries,
        "twin_effects": len(app.state.book.state), "clock": "continuous, speed 1",
        "note": "Water choice is test configuration, not reviewed hydraulic safety" if sid == "S02" else ""})
    assert not app.state.book.state, "No unsigned/reconstructed approvals may actuate"
    assert result["decisions"], result
    assert all(d["status"] in {"alert", "blocked"} for d in result["decisions"])
    if sid in {"S02", "S05"}:
        assert all(d["status"] == "blocked" for d in result["decisions"]), result


async def native_authorization(twin, guardian_url, *, wrong_run=False):
    app, url = twin
    httpx.post(guardian_url + "/api/reset", timeout=10).raise_for_status()
    client = MCPPeer(url, KEY)
    batch = await client.call_tool("get_readings", {})
    action = next(a for a in (await client.call_tool("list_actions", {}))["actions"]
                  if a["action"] == "set_valve_position")
    row = next(r for r in batch["readings"] if r["sensor"] == "water_level"
               and r["node_id"] in action["target_nodes"])
    scored = await post_batch(guardian_url, {**batch, "count": 1, "readings": [row]})
    assert scored["results"][0]["evaluation"]["guardian"]["trust_score"] >= .85
    payload = {"run_id": "wrong-run" if wrong_run else batch["run_id"],
               "reading_id": row["reading_id"], "action": action["action"],
               "parameters": {"position": 30.0}, "risk_level": "R3", "domain": "Water"}
    response = httpx.post(guardian_url + "/api/actions/authorize", json=payload,
                         headers={"Authorization": f"Bearer {API_KEY}"}, timeout=15)
    return app, client, row, payload, response


async def token_crosscheck(twin, guardian_url):
    app, client, row, payload, response = await native_authorization(twin, guardian_url)
    response.raise_for_status()
    reply = response.json()
    assert reply["decision"] == "approved"
    token = reply["token"]
    public = serialization.load_pem_public_key(
        __import__("pathlib").Path(os.environ["GUARDIAN_TOKEN_PUBLIC_KEY"]).read_bytes())
    parts = token.split(".")
    public.verify(base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4)),
                  f"{parts[0]}.{parts[1]}".encode())
    app.state.settings.config.tokens.mode = "signed"
    app.state.settings.config.tokens.guardian_public_key = base64.b64encode(
        public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    intent = {"action": payload["action"], "targets": [row["node_id"]], "params": payload["parameters"]}
    await client.call_tool("preview_action", intent)
    result = await client.call_tool("actuate", {**intent, "token": token,
                                                 "idempotency_key": "actual-guardian-v2-crosscheck"})
    claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    save("guardian-twin-token", {"guardian_decision": reply["decision"],
        "actual_signature_verified": True, "prefix": parts[0], "claim_names": sorted(claims),
        "guardian_iat_epoch": claims["iat"], "twin_clock": await client.call_tool("get_clock", {}),
        "result": result, "twin_effects": len(app.state.book.state)})
    return result


async def test_actual_guardian_signature_and_twin_refusal_are_reproduced(twin, guardian_url):
    receipt = await token_crosscheck(twin, guardian_url)
    assert receipt["status"] == "rejected" and receipt["code"] == "TOKEN_INVALID", receipt


async def test_new_ingestion_endpoint_requires_configured_key(twin, guardian_url):
    _, url = twin
    batch = await MCPPeer(url, KEY).call_tool("get_readings", {})
    response = httpx.post(guardian_url + "/api/integrations/twin/event",
                         json={"event": "readings", "data": batch}, timeout=10)
    assert response.status_code == 401


async def test_actual_guardian_stream_bridge_can_connect(twin, guardian_url):
    _, url = twin
    env = os.environ.copy()
    env.update(TWIN_BASE_URL=url.removesuffix("/mcp"), GUARDIAN_TWIN_BEARER_KEY=GKEY,
               GUARDIAN_LOCAL_URL=guardian_url, GUARDIAN_API_BEARER_KEY=API_KEY,
               PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    env.pop("BRAIN_VERDICT_URL", None)
    env.pop("GUARDIAN_BRAIN_BEARER_KEY", None)
    log = OUT / "guardian-bridge.log"
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen([os.environ["CIVIS_TEST_GUARDIAN_PYTHON"],
            str(GUARDIAN / "src/twin_runner.py")], cwd=GUARDIAN, env=env,
            stdout=stream, stderr=stream, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            async with asyncio.timeout(25):
                while True:
                    assert process.poll() is None, "Guardian bridge exited; inspect its local log"
                    if '"processed":' in log.read_text(encoding="utf-8"):
                        break
                    await asyncio.sleep(.2)
        finally:
            process.terminate()
            process.wait(timeout=10)
    save("guardian-bridge", {"received_actual_twin_batch": True,
                              "verdict_webhook": "disabled; existing Brain pull adapter is used"})


async def test_missing_http_evidence_is_a_clear_blocker(guardian_url):
    peer = actual_guardian(guardian_url)
    try:
        await peer.call_tool(SCORE_TOOL, {"run_id": "unknown", "readings": [{
            "run_id": "unknown", "reading_id": "not-present"}]})
    except BrainError as error:
        assert error.code == "GUARDIAN_EVIDENCE_UNAVAILABLE"
    else:
        pytest.fail("Missing evidence was trusted")


async def test_mixed_five_scenarios_with_actual_peers(twin, guardian_url):
    app, url = twin
    httpx.post(guardian_url + "/api/reset", timeout=10).raise_for_status()
    cases, providers = {}, {}
    for sid in ("S01", "S02", "S03", "S04", "S05"):
        client, case, _, provider, _ = await prepare(url, sid)
        cases[sid], providers[sid] = case, provider

    class PerIncidentRecordedPlan:
        async def generate(self, context):
            sid = {"flood": "S02", "medical": "S05", "congestion": "S01"}[
                context.incidents[0].kind]
            return await providers[sid].generate(context)

    runtime = build_runtime(twin=client, guardian=actual_guardian(guardian_url),
        provider=PerIncidentRecordedPlan(), policies={sid: c["policy"] for sid, c in cases.items()},
        features={"enabled_scenario_ids": list(cases), "mock_integration_profile": True,
            "guardian_contract_confirmed": True, "guardian_score_tool": SCORE_TOOL,
            "guardian_token_tool": APPROVAL_TOOL, "preview_tool": "preview_action",
            "peer_timeout_seconds": 15, "max_evidence_age_seconds": 60,
            "ai_max_calls_per_run": 10}, artifact_dir=OUT / "actual-three-processes/mixed")
    try:
        batches = await capture_batches(url, 2)
        for batch in batches:
            await post_batch(guardian_url, batch)
            result = await runtime.evaluate_tick(ReadingsBatch.model_validate(batch))
        save("joint-mixed-five", {"result": result.model_dump(),
            "twin_effects": len(app.state.book.state), "guardian": "ACTUAL Guardian diagnostic layout",
            "planner": "per-incident recorded control", "clock": "continuous"})
        assert not app.state.book.state
        assert len(result.decisions) >= 5
        assert any(d.status == "alert" and "air pollution" in d.reason for d in result.decisions)
        assert any(d.peer_code == "GUARDIAN_TOKEN_CONTRACT_UNSUPPORTED" for d in result.decisions)
        assert any(d.peer_code == "GUARDIAN_EVIDENCE_REJECTED" for d in result.decisions)
    finally:
        await runtime.close()
