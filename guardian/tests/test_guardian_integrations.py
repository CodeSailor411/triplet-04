"""Deterministic unit and local integration tests for Guardian G5-G8."""
from __future__ import annotations

import json
import io
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from action_policy import ActionPolicy, ActionPolicyError  # noqa: E402
from audit_log import JsonlAuditLog  # noqa: E402
from guardian_policy import TrustPolicy  # noqa: E402
from token_service import ActionTokenService, TokenError  # noqa: E402
from twin_adapter import normalize_twin_reading  # noqa: E402


def test_trust_policy_boundaries_and_validation():
    policy = TrustPolicy()
    assert [policy.classify(x) for x in [0, .3, .3000001, .7, .7000001, 1]] == [
        "compromised", "compromised", "suspect", "suspect", "trusted", "trusted"]
    with pytest.raises(ValueError):
        policy.classify(float("nan"))
    with pytest.raises(ValueError):
        TrustPolicy(trusted_min=.2, suspect_min=.3)


def test_token_issue_signature_binding_expiry_and_replay():
    now = [100.0]
    keys = Ed25519PrivateKey.generate()
    issuer = ActionTokenService(private_key=keys, clock=lambda: now[0])
    verifier = ActionTokenService(public_key=keys.public_key(), clock=lambda: now[0])
    token, claims = issuer.issue(run_id="run-1", action="set_priority_mode", parameters={"mode": "normal"},
                                 reading_id="read-1", trust_score=.9, risk_level="R1")
    assert verifier.verify(token, action="set_priority_mode", parameters={"mode": "normal"}, consume=False) == claims
    with pytest.raises(TokenError, match="action_or_parameters_mismatch"):
        verifier.verify(token, action="set_priority_mode", parameters={"mode": "emergency_first"})
    now[0] = 160.0
    with pytest.raises(TokenError, match="expired_token"):
        verifier.verify(token, action="set_priority_mode", parameters={"mode": "normal"})

    now[0] = 101
    replay_verifier = ActionTokenService(public_key=keys.public_key(), clock=lambda: now[0])
    replay_verifier.verify(token, action="set_priority_mode", parameters={"mode": "normal"})
    with pytest.raises(TokenError, match="replayed_token"):
        replay_verifier.verify(token, action="set_priority_mode", parameters={"mode": "normal"})
    forged = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(TokenError):
        replay_verifier.verify(forged, action="set_priority_mode", parameters={"mode": "normal"})


def test_action_alias_policy_power_cap_and_rollback_pools():
    policy = ActionPolicy()
    assert policy.normalize("set_failover") == "set_priority_mode"
    assert policy.normalize("set_collection_priority") == "send_collection_truck"
    with pytest.raises(ActionPolicyError, match="action_risk_level_unconfirmed"):
        policy.authorize(run_id="r", action="set_failover", parameters={"mode": "normal"},
                         trust_score=.9, risk_level="R1", domain="Telecom")
    with pytest.raises(ActionPolicyError, match="action_not_allowlisted"):
        policy.normalize("launch_missiles")
    for _ in range(3):
        policy.authorize(run_id="p", action="set_grid_switch", parameters={"state": "open"},
                         trust_score=.9, risk_level="NONE", domain="Power")
    with pytest.raises(ActionPolicyError, match="power_action_cap_exceeded"):
        policy.authorize(run_id="p", action="set_grid_switch", parameters={"state": "closed"},
                         trust_score=.9, risk_level="NONE", domain="Power")
    assert policy.authorize(run_id="p-next", action="set_grid_switch", parameters={"state": "closed"},
                            trust_score=.9, risk_level="NONE", domain="Power")[0] == "set_grid_switch"
    assert policy.reserve_rollback("Telecom", "t1") == 1
    assert policy.reserve_rollback("Telecom", "t1") == 1
    policy.reserve_rollback("Telecom", "t2")
    policy.reserve_rollback("Telecom", "t3")
    with pytest.raises(ActionPolicyError, match="rollback_pool_exhausted"):
        policy.reserve_rollback("Telecom", "t4")
    assert policy.release_rollback("Telecom", "t1") == 2
    assert policy.reserve_rollback("Waste", "w1") == 1


@pytest.mark.parametrize(("risk", "action", "domain", "parameters", "minimum"), [
    ("R1", "set_signal_plan", "Traffic", {"plan": "normal"}, .5),
    ("R2", "dispatch", "Emergency", {"unit_type": "police", "destination": "CALL-01", "units": 1}, .7),
    ("R3", "set_valve_position", "Water", {"position": 50}, .85),
])
def test_risk_minimum_boundaries_are_independent_of_verdict_classification(risk, action, domain, parameters, minimum):
    policy = ActionPolicy()
    assert policy.authorize(run_id="boundary", action=action, parameters=parameters,
                            trust_score=minimum, risk_level=risk, domain=domain)[0] == action
    with pytest.raises(ActionPolicyError, match="risk_minimum_score_not_met"):
        policy.authorize(run_id="below", action=action, parameters=parameters,
                         trust_score=minimum - .0001, risk_level=risk, domain=domain)
    assert policy.trust.classify(.7) == "suspect"
    assert policy.trust.classify(.70001) == "trusted"


def test_audit_correlates_and_redacts(tmp_path):
    path = JsonlAuditLog(tmp_path).record(run_id="test-run", event_type="action_decision",
        reading_id="reading-1", trust_score=.9, verdict="trusted", action="set_priority_mode",
        decision="approved", reason=None, caused_by="reading-1",
        data={"token_id": "id", "token": "FULLTOKEN", "authorization": "Bearer secret"})
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["caused_by"] == "reading-1"
    assert record["data"]["token_id"] == "id"
    assert "FULLTOKEN" not in path.read_text(encoding="utf-8")
    assert "Bearer secret" not in path.read_text(encoding="utf-8")


def test_twin_event_normalization_and_rejection():
    reading = normalize_twin_reading({"run_id": "r", "reading_id": "id", "device_id": "d",
        "node_id": "n", "timestamp": "2026-10-22T12:00:00Z", "tick": 1,
        "sensor": "water_level", "value": 120, "unit": "cm", "lat": 36.5, "lon": 11.5})
    assert reading["sensor_type"] == "water_level"
    assert reading["location"] == {"lat": 36.5, "lng": 11.5}
    with pytest.raises(ValueError, match="no Guardian mapping"):
        normalize_twin_reading({"run_id": "r", "reading_id": "id", "device_id": "d",
            "timestamp": "2026-10-22T12:00:00Z", "tick": 1, "sensor": "network_load",
            "value": 1, "unit": "%", "lat": 1, "lon": 1})


def test_sse_reconnect_and_bearer_auth():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if len(requests) > 1:
                self.wfile.write(b"event: hello\ndata: {\"run_id\":\"r\"}\n\n")
                self.wfile.flush()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from twin_adapter import TwinSSEAdapter
        adapter = TwinSSEAdapter(base_url=f"http://127.0.0.1:{server.server_port}", bearer_key="test-key",
                                 timeout=1, max_retries=1, retry_base_seconds=.001)

        async def first_event():
            async for event in adapter.events():
                return event

        event = __import__("asyncio").run(__import__("asyncio").wait_for(first_event(), timeout=3))
        assert event["event"] == "hello"
        assert requests == ["Bearer test-key", "Bearer test-key"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_sse_malformed_json_is_rejected():
    from twin_adapter import TwinConnectionError, TwinSSEAdapter
    adapter = TwinSSEAdapter(base_url="http://127.0.0.1", bearer_key="key")
    with pytest.raises(TwinConnectionError, match="malformed JSON"):
        __import__("asyncio").run(adapter._read_event(io.BytesIO(b"event: readings\ndata: nope\n\n")))


def test_key_loader_rejects_invalid_material(monkeypatch, tmp_path):
    from token_service import ActionTokenService
    bad = tmp_path / "bad.pem"
    bad.write_text("not a PEM key", encoding="utf-8")
    monkeypatch.setenv("GUARDIAN_TOKEN_PRIVATE_KEY", str(bad))
    monkeypatch.delenv("GUARDIAN_TOKEN_PUBLIC_KEY", raising=False)
    with pytest.raises(ValueError):
        ActionTokenService.from_env()
    with pytest.raises(ValueError, match="does not match"):
        ActionTokenService(private_key=Ed25519PrivateKey.generate(), public_key=Ed25519PrivateKey.generate().public_key())


def test_audit_concurrent_lines_remain_valid(tmp_path):
    audit = JsonlAuditLog(tmp_path)
    workers = [threading.Thread(target=lambda n=n: audit.record(
        run_id="concurrent", event_type="decision", reading_id=f"r-{n}", trust_score=.8,
        verdict="trusted", action=None, decision="evaluated", reason=None,
        caused_by=f"r-{n}")) for n in range(40)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    records = [json.loads(line) for line in (tmp_path / "concurrent.guardian.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(records) == 40


def test_local_twin_event_auth_and_pipeline(monkeypatch, tmp_path):
    import unified_api
    from integration_service import service

    monkeypatch.setenv("GUARDIAN_API_BEARER_KEY", "local-test-secret")
    monkeypatch.setattr(unified_api, "_audit_log", JsonlAuditLog(tmp_path))
    private = Ed25519PrivateKey.generate()
    monkeypatch.setattr(unified_api, "_token_service", ActionTokenService(private_key=private))
    service.reset()
    body = {"event": "readings", "data": {"run_id": "local-1", "readings": [{
        "run_id": "local-1", "reading_id": "twin-reading-1", "device_id": "sensor-1",
        "node_id": "PWR-01", "timestamp": 1800000000, "tick": 1, "sensor": "load_kw",
        "value": 450, "unit": "kW", "lat": 37.27, "lon": 9.87,
    }]}}
    # Do not enter lifespan here: the legacy MCP session manager is one-shot,
    # and the existing suite owns its own session-scoped TestClient lifecycle.
    client = TestClient(unified_api.app)
    assert client.post("/api/integrations/twin/event", json=body).status_code == 401
    response = client.post("/api/integrations/twin/event", json=body,
                           headers={"Authorization": "Bearer local-test-secret"})
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["reading_id"] == "twin-reading-1"
    authorization = client.post("/api/actions/authorize", json={
        "run_id": "local-1", "reading_id": "twin-reading-1", "action": "set_grid_switch",
        "parameters": {"state": "open"}, "risk_level": "NONE", "domain": "Power",
    }, headers={"Authorization": "Bearer local-test-secret"})
    assert authorization.status_code == 200, authorization.text
    approved = authorization.json()
    verification = client.post("/api/actions/verify", json={
        "token": approved["token"], "action": "set_grid_switch", "parameters": {"state": "open"},
    }, headers={"Authorization": "Bearer local-test-secret"})
    assert verification.status_code == 200, verification.text
    assert verification.json()["token_id"] == approved["token_id"]
    log = (tmp_path / "local-1.guardian.jsonl").read_text(encoding="utf-8")
    assert approved["token"] not in log
    assert f'"token_id":"{approved["token_id"]}"' in log
    for node in ("w1", "w2", "w3"):
        reserved = client.post(f"/api/actions/rollback-pool/Waste/{node}", json={
            "run_id": "local-1", "reading_id": "twin-reading-1",
        }, headers={"Authorization": "Bearer local-test-secret"})
        assert reserved.status_code == 200
    exhausted = client.post("/api/actions/rollback-pool/Waste/w4", json={
        "run_id": "local-1", "reading_id": "twin-reading-1",
    }, headers={"Authorization": "Bearer local-test-secret"})
    assert exhausted.status_code == 409
    assert (tmp_path / "local-1.guardian.jsonl").is_file()
    client.close()
    service.reset()
