"""Required shipped-service gate with independent feeds and original partner code.

The Twin's public sensor-model configuration creates virtual true conditions.
No fake_reading attack is reclassified as a trusted physical incident. Guardian
runs its own delivered SSE bridge. Brain is constructed through its shipped app
and Settings/bootstrap; a labelled recorded planner avoids external AI cost.
Unmet partner prerequisites are ordinary failures, never skips or fake approval.
"""

import asyncio
import copy
import hashlib
import json
import os
import shutil
import subprocess
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from civis_mock_peers.http import serve
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from civis_brain.app import create_app
from civis_brain.contracts import Plan
from civis_brain.integration import bootstrap
from civis_brain.settings import Settings

from .test_partners import GKEY, GUARDIAN, KEY, OUT, ROOT, SKEY, TWIN, MCPPeer
from .test_v3_joint import API_KEY, BRAIN_KEY, actual_guardian

INBOUND = {"twin": "test-live-twin-to-brain", "guardian": "test-live-guardian-to-brain",
           "scenario": "test-live-scenario-to-brain"}
WORKFLOW_SCOPE = {
    "S01": "Actual Guardian authorization and Twin signal commit are required",
    "S02": "Virtual valve command acceptance only; no hydraulic mitigation claim",
    "S03": "Explicit POWER_EVIDENCE_UNCONFIRMED warning only; does not prove trusted Power incident or switching",
    "S04": "Trusted sustained PM2.5 plan alert after actual Guardian verdicts; an evidence warning does not pass",
    "S05": "Actual availability trust, Guardian authorization and Twin Medical dispatch are required",
}


def write_evidence(directory, name, data):
    (directory / (name + ".json")).write_text(
        json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")


@pytest.fixture
def shipped_twin(request):
    """Native public profile overrides, not source edits or fabricated readings."""
    from twin.app import create_app as twin_app
    from twin.settings import Secrets, load_config
    from twin.settings import Settings as TwinSettings

    sid = getattr(request, "param", "S03")
    directory = OUT / "shipped" / request.node.name.replace("[", "-").replace("]", "")
    directory.mkdir(parents=True, exist_ok=True)
    config = load_config(TWIN / "config/twin.yaml")
    config.clock.autorun, config.clock.speed = True, 1
    config.logging.enabled = True
    config.logging.parts_dir = str(directory / "twin-logs")
    config.logging.merged_dir = str(directory / "merged-logs")
    config.tokens.mode = "signed"
    config.tokens.guardian_public_key = os.environ["GUARDIAN_TOKEN_PUBLIC_KEY"]
    overrides = {
        "S01": ("congestion_index", 95), "S02": ("water_level", 180),
        "S03": ("load_kw", 650), "S04": ("pm25", 120),
        "S05": ("emergency_calls", None),
    }
    sensor, value = overrides[sid]
    profile = config.sensor_model.profiles[sensor]
    if sid == "S05":
        profile.channels["medical"] = 2
    else:
        profile.base = value
    # Keep normal noise, bias, dynamics and all advertised devices/channels.
    # Only the public truth baseline changes, so Guardian remains authoritative.
    write_evidence(directory, "test-profile", {
        "scenario_id": sid, "source_modified": False,
        "sensor_model_override": {sensor: {"channels.medical": 2} if sid == "S05" else {"base": value}},
        "clock": {"autorun": True, "speed": 1, "tick_seconds": config.clock.tick_seconds},
        "input": "native observed readings from configured virtual true conditions",
        "guardian_policy_override": False,
    })
    app = twin_app(TwinSettings(config=config, secrets=Secrets(
        _env_file=None, city_brain=KEY, guardian=GKEY, scenario=SKEY)))
    with serve(app) as url:
        yield SimpleNamespace(app=app, url=url, sid=sid, directory=directory)


@contextmanager
def guardian_bridge(twin_url, guardian_url, directory):
    """Start Guardian's delivered bridge; never post evidence on its behalf."""
    env = {**os.environ, "TWIN_BASE_URL": twin_url.removesuffix("/mcp"),
           "GUARDIAN_TWIN_BEARER_KEY": GKEY, "GUARDIAN_LOCAL_URL": guardian_url,
           "GUARDIAN_API_BEARER_KEY": API_KEY, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
    for name in ("PYTHONPATH", "BRAIN_VERDICT_URL", "GUARDIAN_BRAIN_BEARER_KEY"):
        env.pop(name, None)
    log = directory / "guardian-bridge.log"
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            [os.environ["CIVIS_TEST_GUARDIAN_PYTHON"], str(GUARDIAN / "src/twin_runner.py")],
            cwd=GUARDIAN, env=env, stdout=stream, stderr=stream,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            yield process, log
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


class NativeIntentPlanner:
    """Recorded intent selection only; all evidence and approval are real peers."""
    async def generate(self, context):
        kind = context.incidents[0].kind
        name = {"congestion": "set_signal_plan", "flood": "set_valve_position",
                "medical": "dispatch"}[kind]
        action = next(item for item in context.actions if item.action == name)
        source_ids = [row.reading_id for row in context.evidence_readings]
        if kind == "flood":
            incident = next(item for item in context.incidents if item.facts.get("supported_valve_actions"))
            choice = incident.facts["supported_valve_actions"][0]
            targets, params = choice["targets"], choice["params"]
            source_ids = incident.source_reading_ids
        elif kind == "medical":
            eligible = {row.node_id for row in context.evidence_readings
                        if row.sensor == "units_free" and row.channel == "ambulance"
                        and row.value is not None and row.value >= 1}
            targets = [next(node for node in action.target_nodes if node in eligible)]
            params = {"unit_type": "ambulance", "destination": context.incidents[0].node_ids[0], "units": 1}
        else:
            nodes = {node.node_id: node for node in context.nodes}
            eligible = [node for node in action.target_nodes if len(nodes[node].domains) == 1]
            targets = [next(iter(eligible or action.target_nodes))]
            params = {"plan": next(item for item in action.params if item["name"] == "plan")["choices"][0]}
        return Plan.model_validate({"proposals": [{
            "action": name, "targets": targets, "params": params, "risk": action.risk,
            "preview_required": action.preview_required,
            "source_reading_ids": source_ids,
            "reason": "Recorded acceptance plan using native evidence and published manifest",
        }], "alerts": []})


def observe_actuations(runtime):
    """Passive test-only capture; original signed requests stay in memory only."""
    requests = []
    original = runtime.twin.call_tool

    async def call_tool(name, arguments):
        if name == "actuate":
            requests.append(copy.deepcopy(arguments))
        return await original(name, arguments)

    runtime.twin.call_tool = call_tool
    return requests


@asynccontextmanager
async def shipped_stack(twin, monkeypatch, *, events_url=None, evidence_age=60):
    directory = twin.directory
    config_root = directory / "brain-workspace"
    shutil.copytree(ROOT / "config", config_root / "config", dirs_exist_ok=True)
    profile = ROOT / "config/integration/twin-mock-3.json"
    overrides = json.loads(profile.read_text(encoding="utf-8")) if profile.exists() else {}
    for sid in ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08"):
        overrides.setdefault(sid, {})["enabled"] = sid == twin.sid
    override_file = config_root / "acceptance-policies.json"
    override_file.write_text(json.dumps(overrides), encoding="utf-8")
    write_evidence(directory, "brain-policy", overrides)
    monkeypatch.setattr(bootstrap, "configured_provider", lambda *_: NativeIntentPlanner())
    with actual_guardian(twin.url, audit_dir=directory / "guardian-logs") as guardian_url:
        with guardian_bridge(twin.url, guardian_url, directory) as (bridge, bridge_log):
            settings = Settings(_env_file=None, brain_config_root=str(config_root),
                peer_mode="live", llm_mode="gemini", gemini_api_key="recorded-test-planner-only",
                brain_twin_caller_key=INBOUND["twin"], brain_guardian_caller_key=INBOUND["guardian"],
                brain_scenario_key=INBOUND["scenario"], twin_mcp_url=twin.url,
                twin_events_url=events_url or twin.url.removesuffix("/mcp") + "/events",
                twin_brain_key=KEY, twin_feed_enabled=True, mock_integration_profile=True,
                guardian_mcp_url=guardian_url + "/mcp", guardian_brain_key=BRAIN_KEY,
                guardian_transport="mcp_v3", guardian_contract_confirmed=True,
                scenario_policy_file=str(override_file), max_evidence_age_seconds=evidence_age,
                peer_timeout_seconds=8, ai_max_calls_per_run=20)
            app = create_app(settings)
            actuate_requests = observe_actuations(app.state.runtime)
            with serve(app) as brain_url:
                stack = SimpleNamespace(twin=twin, app=app, runtime=app.state.runtime,
                    brain=MCPPeer(brain_url, INBOUND["scenario"], 12),
                    guardian=MCPPeer(guardian_url + "/mcp", BRAIN_KEY, 8),
                    guardian_url=guardian_url, bridge=bridge, bridge_log=bridge_log,
                    brain_url=brain_url.removesuffix("/mcp"), directory=directory,
                    actuate_requests=actuate_requests)
                try:
                    yield stack
                finally:
                    async with httpx.AsyncClient(timeout=3) as http:
                        health = (await http.get(stack.brain_url + "/health")).json()
                    write_evidence(directory, "shipped-result", {
                        "health": health, "decisions": [item.model_dump() for item in stack.runtime.decisions.values()],
                        "twin_committed_actions": len(twin.app.state.book.committed),
                        "twin_action_sequence": twin.app.state.book.seq,
                        "twin_actuator_state_entries": len(twin.app.state.book.state),
                        "guardian_bridge_exit": bridge.poll(), "manual_guardian_ingestion": False,
                        "planner": "recorded intent selection; not live Gemini",
                        "workflow_scope": WORKFLOW_SCOPE[twin.sid],
                    })


async def wait_feed(stack, evaluated=3, seconds=25):
    async with httpx.AsyncClient(timeout=3) as http:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if stack.bridge.poll() is not None:
                pytest.fail("GUARDIAN_FEED_BRIDGE_EXITED: inspect guardian-bridge.log; no manual ingestion substituted")
            health = (await http.get(stack.brain_url + "/health")).json()
            if health["feed"].get("evaluated", 0) >= evaluated:
                return health
            if health["feed"].get("state") == "processor_failed":
                pytest.fail("BRAIN_PROCESSOR_FAILED: shipped feed stopped")
            await asyncio.sleep(.1)
    pytest.fail("BRAIN_LIVE_FEED_TIMEOUT: shipped app did not evaluate required native batches")


async def require_action(stack):
    await wait_feed(stack)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        completed = [(key, receipt) for key, receipt in list(stack.runtime.intents.items())
                     if receipt.get("status") == "committed"]
        if completed:
            key, brain_receipt = completed[0]
            requests = [item for item in list(stack.actuate_requests) if item.get("idempotency_key") == key]
            assert requests, "BRAIN_COMMIT_WITHOUT_OBSERVED_ACTUATE"
            request = requests[0]
            assert all(item == request for item in requests), "CHANGED_REQUEST_UNDER_SAME_KEY"
            book = stack.twin.app.state.book
            saved = book.store.get_answer(stack.runtime.run_id, "city_brain", key)
            assert saved is not None, "BRAIN_COMMIT_WITHOUT_TWIN_IDEMPOTENCY_RECEIPT"
            receipt = json.loads(saved[1])
            assert receipt["status"] == "committed"
            assert receipt["action_id"] in book.committed
            assert receipt["action_id"] == brain_receipt.get("action_id")
            assert all(receipt[field] == request[field] for field in ("action", "targets", "params"))
            write_evidence(stack.directory, "actual-commit-proof", {
                "idempotency_key": key, "receipt": receipt,
                "committed_action_ids": sorted(book.committed), "action_sequence": book.seq,
                "proof": "Actual Twin commit history and key-indexed receipt, not just Brain status or last actuator state"})
            return request
        await asyncio.sleep(.1)
    codes = sorted({item.peer_code or item.status for item in stack.runtime.decisions.values()})
    pytest.fail("LIVE_ACTION_PREREQUISITE_FAILED: " + repr(codes))


async def test_commit_proof_survives_runtime_removing_finished_request(monkeypatch, tmp_path):
    """Harness regression only, not a replacement for the real-service gate."""
    request = {"action": "set_signal_plan", "targets": ["TRA-01"], "params": {"plan": "normal"},
               "idempotency_key": "original-key", "token": "PRIVATE_TEST_TOKEN"}
    receipt = {"status": "committed", "action_id": "actual-action", "run_id": "r1",
               "action": request["action"], "targets": request["targets"], "params": request["params"]}
    forwarded = []

    async def actual_call(name, arguments):
        forwarded.append((name, arguments))
        return receipt

    runtime = SimpleNamespace(twin=SimpleNamespace(call_tool=actual_call), run_id="r1",
        intents={"original-key": receipt}, sent_requests={})
    captured = observe_actuations(runtime)
    assert await runtime.twin.call_tool("actuate", request) is receipt
    assert forwarded[0][1] is request
    assert captured[0] == request and captured[0] is not request
    indexes = []

    def get_answer(run_id, caller, key):
        indexes.append((run_id, caller, key))
        return "fingerprint", json.dumps(receipt)

    async def feed_ready(*_):
        return None

    monkeypatch.setitem(globals(), "wait_feed", feed_ready)
    book = SimpleNamespace(store=SimpleNamespace(get_answer=get_answer),
                           committed={"actual-action"}, seq=1)
    stack = SimpleNamespace(runtime=runtime, actuate_requests=captured, directory=tmp_path,
                            twin=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(book=book))))
    assert await require_action(stack) == request
    assert indexes == [("r1", "city_brain", "original-key")]
    assert runtime.sent_requests == {}
    assert "PRIVATE_TEST_TOKEN" not in (tmp_path / "actual-commit-proof.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("shipped_twin", ["S01", "S02", "S03", "S04", "S05"], indirect=True)
async def test_shipped_five_native_workflows(shipped_twin, monkeypatch):
    async with shipped_stack(shipped_twin, monkeypatch) as stack:
        await wait_feed(stack)
        capabilities = await stack.brain.call_tool("get_capabilities", {})
        assert set(capabilities["implemented_tools"]) == set(await stack.brain.list_tool_names())
        await stack.brain.call_tool("get_active_incidents", {"run_id": stack.runtime.run_id})
        decisions = list(stack.runtime.decisions.values())
        expected = "alert" if shipped_twin.sid in {"S03", "S04"} else "committed"
        if expected == "committed":
            await require_action(stack)
            decisions = list(stack.runtime.decisions.values())
        def qualifies(item):
            if shipped_twin.sid == "S03":
                return (item.status == "alert" and item.peer_code == "EVIDENCE_WARNING"
                        and item.reason.startswith("POWER_EVIDENCE_UNCONFIRMED:"))
            if shipped_twin.sid == "S04":
                return (item.status == "alert" and item.peer_code is None
                        and bool(item.source_reading_ids)
                        and "Sustained reported air pollution" in item.reason)
            return item.status == expected

        # Three observed batches prove reception, not completion of Guardian's
        # independently started feed reader or the declared recovery budget.
        # Observe real progress before declaring an alert workflow unavailable.
        started = time.monotonic()
        deadline = started + 20
        if shipped_twin.sid == "S04":
            while not any(qualifies(item) for item in decisions) and time.monotonic() < deadline:
                await asyncio.sleep(.1)
                decisions = list(stack.runtime.decisions.values())
        write_evidence(stack.directory, "workflow-observation", {
            "scenario_id": shipped_twin.sid, "scope": WORKFLOW_SCOPE[shipped_twin.sid],
            "outcome_wait_seconds": time.monotonic() - started,
            "outcome_wait_budget_seconds": 20 if shipped_twin.sid == "S04" else 0,
            "qualified_outcomes": sum(qualifies(item) for item in decisions),
        })
        assert any(qualifies(item) for item in decisions), [item.model_dump() for item in decisions]
        decision = next(item for item in decisions if qualifies(item))
        explanation = await stack.brain.call_tool("explain_decision", {"decision_id": decision.decision_id})
        assert explanation["decision"]["decision_id"] == decision.decision_id
        assert not (stack.directory / "brain-workspace/mocks").exists()


class FeedFault:
    """Test-only transport fault; native SSE event bytes and credentials are retained."""
    def __init__(self, twin_url, delay=0):
        self.url, self.delay = twin_url.removesuffix("/mcp") + "/events", delay
        self.drop_next = False

    def app(self):
        app = FastAPI()

        @app.get("/events")
        async def events(request: Request):
            async def relay():
                async with httpx.AsyncClient(timeout=20) as client:
                    async with client.stream("GET", self.url, headers={
                        "Authorization": request.headers.get("authorization", "")}) as response:
                        response.raise_for_status()
                        block = []
                        async for line in response.aiter_lines():
                            block.append(line)
                            if not line:
                                if self.drop_next:
                                    self.drop_next = False
                                    return
                                if self.delay:
                                    await asyncio.sleep(self.delay)
                                yield "\n".join(block) + "\n"
                                block = []
            return StreamingResponse(relay(), media_type="text/event-stream")
        return app


@pytest.mark.parametrize("shipped_twin", ["S01"], indirect=True)
async def test_shipped_stale_native_feed_cannot_actuate(shipped_twin, monkeypatch):
    fault = FeedFault(shipped_twin.url, delay=2.1)
    with serve(fault.app()) as proxy:
        async with shipped_stack(shipped_twin, monkeypatch,
                events_url=proxy.removesuffix("/mcp") + "/events", evidence_age=1) as stack:
            await wait_feed(stack, evaluated=1)
            assert any(item.peer_code == "EVIDENCE_STALE" for item in stack.runtime.decisions.values())
            assert not shipped_twin.app.state.book.committed


@pytest.mark.parametrize("shipped_twin", ["S01"], indirect=True)
async def test_shipped_sse_reconnect_invalidates_context(shipped_twin, monkeypatch):
    fault = FeedFault(shipped_twin.url)
    with serve(fault.app()) as proxy:
        async with shipped_stack(shipped_twin, monkeypatch,
                events_url=proxy.removesuffix("/mcp") + "/events") as stack:
            before = await wait_feed(stack, evaluated=2)
            generation = stack.runtime.feed_generation
            original_ids = set(stack.runtime.ledger)
            fault.drop_next = True
            after = await wait_feed(stack, evaluated=before["feed"]["evaluated"] + 3)
            assert after["feed"]["reconnects"] >= 1
            assert stack.runtime.feed_generation > generation
            assert any(item["event"] == "feed_gap" for item in stack.runtime.journal.events)
            assert original_ids <= stack.runtime.invalid_ids, "Reconnect retained old evidence as eligible"
            write_evidence(stack.directory, "reconnect", {
                "before": before["feed"], "after": after["feed"],
                "original_reading_ids": sorted(original_ids),
                "old_evidence_invalidated": True,
                "committed_action_ids": sorted(shipped_twin.app.state.book.committed),
                "authorization": "actual Guardian; a denied action is not reported as a successful action"})


async def test_shipped_missing_evidence_is_refused(shipped_twin, monkeypatch):
    async with shipped_stack(shipped_twin, monkeypatch) as stack:
        await wait_feed(stack, evaluated=1)
        reply = await stack.guardian.call_tool("authorize_action", {
            "run_id": stack.runtime.run_id, "reading_ids": ["never-seen-native-reading"],
            "action": "set_signal_plan", "targets": ["TRA-01"], "params": {"plan": "normal"},
            "risk_level": "R1", "domain": "Traffic", "idempotency_key": "missing-evidence-negative-control"})
        write_evidence(stack.directory, "refusal", {"decision": reply.get("decision"),
            "refusal_code": reply.get("refusal_code"), "token_present": bool(reply.get("token"))})
        assert reply.get("decision") == "refused" and not reply.get("token"), reply
        assert not shipped_twin.app.state.book.committed


@pytest.mark.parametrize("shipped_twin", ["S01"], indirect=True)
async def test_shipped_duplicate_original_action_has_one_effect(shipped_twin, monkeypatch):
    async with shipped_stack(shipped_twin, monkeypatch) as stack:
        request = await require_action(stack)
        book = shipped_twin.app.state.book
        committed_before = sorted(book.committed)
        sequence_before = book.seq
        client = MCPPeer(shipped_twin.url, KEY, 8)
        first = await client.call_tool("actuate", request)
        second = await client.call_tool("actuate", request)
        write_evidence(stack.directory, "duplicate-action", {"first": first, "second": second,
            "committed_action_ids_before": committed_before,
            "committed_action_ids_after": sorted(book.committed),
            "action_sequence_before": sequence_before, "action_sequence_after": book.seq,
            "idempotency_key": request["idempotency_key"], "original_token_forwarded": True})
        assert first == second and first["status"] == "committed"
        assert first["action_id"] in committed_before
        assert sorted(book.committed) == committed_before
        assert book.seq == sequence_before


async def test_shipped_guardian_containment_reaches_twin_and_brain(shipped_twin, monkeypatch):
    async with shipped_stack(shipped_twin, monkeypatch) as stack:
        await wait_feed(stack, evaluated=2)
        row = next(item for item in stack.runtime.ledger.values() if item.sensor == "load_kw")
        async with httpx.AsyncClient(timeout=8) as http:
            response = await http.post(stack.guardian_url + "/quarantine_device/" + row.device_id,
                                      headers={"Authorization": f"Bearer {API_KEY}"})
            response.raise_for_status()
        await asyncio.sleep(2)
        state = await MCPPeer(shipped_twin.url, KEY, 8).call_tool("get_containment_state", {})
        reaches_twin = any(item["device_id"] == row.device_id for item in state["devices"])
        reaches_brain = row.device_id in stack.runtime.blocked_devices
        notices = [item for item in stack.runtime.journal.events
                   if item.get("event") == "containment_notice"
                   and row.device_id in item.get("device_ids", [])]
        polled = [item for item in notices if item.get("event_id", "").startswith(("poll-", "corrections-"))]
        callbacks = [item for item in notices if item not in polled]
        write_evidence(stack.directory, "containment", {"guardian_reply": response.json(),
            "twin_state": state, "brain_invalidated": reaches_brain,
            "brain_invalidation_source": "twin_poll" if polled else "guardian_callback" if callbacks else "not_observed",
            "polled_notice_event_ids": [item["event_id"] for item in polled],
            "guardian_callback_event_ids": [item["event_id"] for item in callbacks],
            "guardian_mcp_callback_observed": bool(callbacks),
            "brain_callback_fabricated": False,
            "requirement": "D14 sensor containment and Brain invalidation; polling is allowed, callback delivery is separate"})
        assert reaches_twin, "GUARDIAN_CONTAINMENT_NOT_PROPAGATED: Guardian reply is not actual Twin containment"
        assert reaches_brain, "BRAIN_CONTAINMENT_NOT_INVALIDATED: check callback or authoritative polling"


async def test_shipped_guardian_key_matches_twin_configuration(shipped_twin, monkeypatch):
    async with shipped_stack(shipped_twin, monkeypatch) as stack:
        async with httpx.AsyncClient(timeout=5) as http:
            capabilities = (await http.get(stack.guardian_url + "/api/capabilities")).json()
        published = capabilities["action_token"]
        key = serialization.load_pem_public_key(published["public_key_pem"].encode())
        expected = serialization.load_pem_public_key(Path(os.environ["GUARDIAN_TOKEN_PUBLIC_KEY"]).read_bytes())
        actual_bytes = key.public_bytes_raw()
        write_evidence(stack.directory, "public-key", {"kid": published["kid"],
            "sha256": hashlib.sha256(actual_bytes).hexdigest(), "private_key_published": False})
        assert actual_bytes == expected.public_bytes_raw()
