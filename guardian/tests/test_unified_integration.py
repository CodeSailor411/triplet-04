"""End-to-end checks for the Guardian + model integration boundary."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from integration_service import service  # noqa: E402
from unified_api import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_service():
    service.reset()
    yield
    service.reset()


def request_body(**changes):
    body = {
        "sensor_id": "power-test",
        "sensor_type": "power_load",
        "value": 450.0,
        "unit": "kW",
        "timestamp": 1_800_000_000.0,
        "location": {"lat": 37.27, "lng": 9.87},
        "sequence_number": 1,
    }
    return {**body, **changes}


def test_valid_reading_uses_saved_model_and_guardian_scorer(client):
    for seq in range(1, 7):
        response = client.post("/ingest", json=request_body(
            value=450 + seq * 0.05,
            timestamp=1_800_000_000.0 + seq * 5,
            sequence_number=seq,
        ))
        assert response.status_code == 200
    response = client.post("/ingest", json=request_body(
        value=452.0, timestamp=1_800_000_030.0, sequence_number=7,
    ))
    assert response.status_code == 200
    evaluation = response.json()["evaluation"]
    assert evaluation["layer_a"]["status"] == "passed"
    assert evaluation["ml"]["status"] == "available"
    assert evaluation["ml"]["probability"] is not None
    assert set(evaluation["ml"]["features"]) == {
        "domain", "value", "z_score", "rate_of_change", "out_of_bounds",
        "correlation_strength", "incident_claimed", "decayed_flags",
        "baseline_dev_norm", "flat_run_len",
    }
    assert evaluation["guardian"]["trust_score"] != evaluation["ml"]["probability"]
    assert evaluation["guardian"]["scoring_breakdown"]["ml_numeric_contribution"] == 0


@pytest.mark.parametrize(("requested_action", "expected_detail"), [
    ("set_signal_plan", None),
    ("action_missing_from_twin", "action_not_in_twin_manifest"),
])
def test_authorize_action_matches_the_twins_action_field_on_a_real_peer(
    client, monkeypatch, start_real_twin_server, tmp_path, requested_action, expected_detail,
):
    import unified_api
    import twin_discovery
    from audit_log import JsonlAuditLog
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from token_service import ActionTokenService

    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GUARDIAN_API_BEARER_KEY", "test-api-key")
    monkeypatch.setattr(unified_api, "_audit_log", JsonlAuditLog(tmp_path))
    monkeypatch.setattr(unified_api, "_token_service", ActionTokenService(private_key=Ed25519PrivateKey.generate()))
    unified_api._twin_discovery_by_run.clear()
    unified_api._twin_delivery_cache.clear()
    unified_api._last_tick_by_run.clear()
    unified_api._latest_twin_run_id = None

    with start_real_twin_server(replies={
        "list_actions": {"actions": [{"action": "set_signal_plan"}]},
    }) as peer:
        monkeypatch.setattr(twin_discovery, "twin_config", lambda: {
            "base_url": peer.base_url, "bearer_key": "test-twin-key", "timeout": 3,
        })
        event = {"event": "readings", "data": {"run_id": "d3-run", "readings": [{
            "run_id": "d3-run", "reading_id": "d3-reading", "device_id": "traffic-1",
            "timestamp": 1_800_000_000, "tick": 1, "sensor": "congestion_index",
            "value": 20, "unit": "percent", "lat": 37.27, "lon": 9.87,
        }]}}
        ingested = client.post("/api/integrations/twin/event", json=event,
            headers={"Authorization": "Bearer test-api-key"})
        assert ingested.status_code == 200, ingested.text
        response = client.post("/api/actions/authorize", json={
            "run_id": "d3-run", "reading_id": "d3-reading", "reading_ids": ["d3-reading"],
            "action": requested_action, "parameters": {"plan": "normal"},
            "targets": ["signal-1"], "idempotency_key": "d3-key",
            "risk_level": "R1", "domain": "Traffic",
        }, headers={"Authorization": "Bearer test-api-key"})

    if expected_detail:
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == expected_detail
    else:
        assert response.status_code == 200, response.text
        assert response.json()["action"] == "set_signal_plan"


def test_twin_manifest_action_entries_normalize_both_configured_aliases():
    import unified_api

    assert unified_api._twin_manifest_actions({"list_actions": {"actions": [
        {"action": "set_failover", "name": "set_signal_plan"},
        {"name": "set_collection_priority"},
    ]}}) == {"set_priority_mode", "send_collection_truck"}


def test_action_tokens_use_fresh_real_twin_clock_for_each_issue_and_verification(
    client, monkeypatch, start_real_twin_server, tmp_path,
):
    import base64
    import json
    import unified_api
    import twin_discovery
    from audit_log import JsonlAuditLog
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from token_service import ActionTokenService

    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GUARDIAN_API_BEARER_KEY", "d4-api-key")
    monkeypatch.setattr(unified_api, "_audit_log", JsonlAuditLog(tmp_path))
    monkeypatch.setattr(unified_api, "_token_service", ActionTokenService(private_key=Ed25519PrivateKey.generate()))
    unified_api._twin_discovery_by_run.clear()
    unified_api._twin_delivery_cache.clear()
    unified_api._last_tick_by_run.clear()
    unified_api._latest_twin_run_id = None
    headers = {"Authorization": "Bearer d4-api-key"}

    def claims(token):
        segment = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))

    with start_real_twin_server() as peer:
        monkeypatch.setattr(twin_discovery, "twin_config", lambda: {
            "base_url": peer.base_url, "bearer_key": "test-twin-key", "timeout": 3,
        })
        event = {"event": "readings", "data": {"run_id": "d4-run", "readings": [{
            "run_id": "d4-run", "reading_id": "d4-reading", "device_id": "traffic-d4",
            "timestamp": 1_800_000_000, "tick": 1, "sensor": "congestion_index",
            "value": 20, "unit": "percent", "lat": 37.27, "lon": 9.87,
        }]}}
        assert client.post("/api/integrations/twin/event", json=event, headers=headers).status_code == 200

        def authorize(key):
            return client.post("/api/actions/authorize", json={
                "run_id": "d4-run", "reading_id": "d4-reading", "reading_ids": ["d4-reading"],
                "action": "set_signal_plan", "parameters": {"plan": "normal"},
                "targets": ["signal-d4"], "idempotency_key": key,
                "risk_level": "R1", "domain": "Traffic",
            }, headers=headers)

        first = authorize("d4-first")
        peer.state["get_clock"] = {"simulated_time": 1_800_000_300.0}
        second = authorize("d4-second")
        assert first.status_code == second.status_code == 200, (first.text, second.text)
        first_claims, second_claims = claims(first.json()["token"]), claims(second.json()["token"])
        assert first_claims["iat"] == 1_800_000_000.0
        assert first_claims["exp"] == 1_800_000_060.0
        assert second_claims["iat"] == 1_800_000_300.0
        assert second_claims["exp"] == 1_800_000_360.0

        valid = client.post("/api/actions/verify", json={
            "token": second.json()["token"], "action": "set_signal_plan",
            "parameters": {"plan": "normal"}, "targets": ["signal-d4"],
            "idempotency_key": "d4-second",
        }, headers=headers)
        assert valid.status_code == 200, valid.text

        peer.state["get_clock"] = {"simulated_time": 1_800_000_361.0}
        expired = client.post("/api/actions/verify", json={
            "token": second.json()["token"], "action": "set_signal_plan",
            "parameters": {"plan": "normal"}, "targets": ["signal-d4"],
            "idempotency_key": "d4-second",
        }, headers=headers)

    assert expired.status_code == 401
    assert expired.json()["detail"] == "expired_token"


@pytest.mark.parametrize("clock_reply", [{}, {"simulated_time": "not-a-clock"}])
def test_authorization_refuses_unavailable_or_unparseable_twin_clock(
    client, monkeypatch, start_real_twin_server, tmp_path, clock_reply,
):
    import unified_api
    import twin_discovery
    from audit_log import JsonlAuditLog
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from token_service import ActionTokenService

    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GUARDIAN_API_BEARER_KEY", "clock-api-key")
    monkeypatch.setattr(unified_api, "_audit_log", JsonlAuditLog(tmp_path))
    monkeypatch.setattr(unified_api, "_token_service", ActionTokenService(private_key=Ed25519PrivateKey.generate()))
    unified_api._twin_discovery_by_run.clear()
    unified_api._twin_delivery_cache.clear()
    unified_api._last_tick_by_run.clear()
    unified_api._latest_twin_run_id = None
    headers = {"Authorization": "Bearer clock-api-key"}

    with start_real_twin_server(replies={"get_clock": clock_reply}) as peer:
        monkeypatch.setattr(twin_discovery, "twin_config", lambda: {
            "base_url": peer.base_url, "bearer_key": "test-twin-key", "timeout": 3,
        })
        event = {"event": "readings", "data": {"run_id": "clock-run", "readings": [{
            "run_id": "clock-run", "reading_id": "clock-reading", "device_id": "traffic-clock",
            "timestamp": 1_800_000_000, "tick": 1, "sensor": "congestion_index",
            "value": 20, "unit": "percent", "lat": 37.27, "lon": 9.87,
        }]}}
        assert client.post("/api/integrations/twin/event", json=event, headers=headers).status_code == 200
        response = client.post("/api/actions/authorize", json={
            "run_id": "clock-run", "reading_id": "clock-reading", "reading_ids": ["clock-reading"],
            "action": "set_signal_plan", "parameters": {"plan": "normal"},
            "targets": ["signal-clock"], "idempotency_key": "clock-key",
            "risk_level": "R1", "domain": "Traffic",
        }, headers=headers)

    assert response.status_code == 503
    assert response.json()["detail"] == "twin_sim_clock_unavailable"


def test_unscored_known_reading_returns_pending_with_last_scored_tick(client, monkeypatch):
    import unified_api
    from guardian.models import SensorReading
    from integration_service import service

    service.reset()
    monkeypatch.setenv("GUARDIAN_VERDICT_RETRY_AFTER_MS", "750")
    first = service.process_reading({
        "sensor_id": "pending-sensor", "sensor_type": "power_load", "value": 450,
        "unit": "kW", "timestamp": 1_800_010_000.0, "location": {"lat": 1, "lng": 1},
        "sequence_number": 1, "reading_id": "pending-scored-1",
    })
    pending_reading = SensorReading(
        sensor_id="pending-sensor", sensor_type="power_load", value=450.1, unit="kW",
        timestamp=1_800_010_005.0, location={"lat": 1, "lng": 1},
        sequence_number=2, reading_id="pending-2",
    )
    service.buffer.add(pending_reading)

    response = client.get("/trust_verdict/pending-sensor/pending-2")
    tool_result = unified_api.brain_get_trust_verdict("pending-2")
    payload = tool_result.model_dump(mode="json")

    assert first["guardian"]["trust_score"] == 1.0
    assert response.status_code == 200
    assert response.json() == {
        "status": "pending", "reading_id": "pending-2",
        "retry_after_ms": 750, "last_scored_tick": 1,
    }
    assert payload == response.json()
    assert "trust_score" not in payload


def test_never_received_reading_still_returns_verdict_not_found(client):
    import unified_api
    from integration_service import service

    service.reset()
    with pytest.raises(ValueError, match="verdict_not_found"):
        unified_api.brain_get_trust_verdict("never-received")
    response = client.get("/trust_verdict/missing-sensor/never-received")
    assert response.status_code == 404
    assert response.json()["detail"] == "verdict_not_found"


def test_authorize_action_reports_guardian_field_names_for_brain_draft_fields(client):
    response = client.post("/api/actions/authorize", json={
        "run_id": "field-error-run", "reading_id": "field-error-reading",
        "source_reading_ids": ["field-error-reading"], "action": "dispatch",
        "parameters": {"unit_type": "ambulance", "destination": "A", "units": 1},
        "risk": "R2", "approved": True, "domain": "Emergency",
    })

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid_authorize_action_request"
    assert {item["field"] for item in body["missing_fields"]} == {"risk_level"}
    unknown = {item["field"]: item["accepted_name"] for item in body["unknown_fields"]}
    assert unknown == {"risk": "risk_level", "source_reading_ids": "reading_ids", "approved": None}


def test_replay_rejection_skips_inference_and_city_brain_blocks(client):
    first = client.post("/ingest", json=request_body())
    assert first.status_code == 200
    replay = client.post("/ingest", json=request_body(reading_id="replay-2"))
    assert replay.status_code == 409
    evaluation = replay.json()["evaluation"]
    assert evaluation["layer_a"]["reason_codes"] == ["replay_or_out_of_order_sequence_number"]
    assert evaluation["ml"]["status"] == "skipped_security_gate"
    assert evaluation["ml"]["probability"] is None
    assert evaluation["city_brain"]["allowed"] is False


def test_required_signature_failure_skips_inference(client):
    response = client.post("/ingest", json=request_body(
        require_signature=True, signature="f" * 64,
    ))
    assert response.status_code == 401
    evaluation = response.json()["evaluation"]
    assert evaluation["layer_a"]["signature"] == "failed"
    assert evaluation["ml"]["status"] == "skipped_security_gate"
    assert evaluation["guardian"] is None


def test_emergency_correlation_runs_through_real_scoring(client):
    response = client.post("/api/simulations/genuine_fire", json={})
    assert response.status_code == 200
    evaluation = response.json()["focus_evaluation"]
    assert evaluation["layer_c"]["expected"] is True
    assert evaluation["layer_c"]["strength"] == 1.0
    assert evaluation["layer_c"]["status"] == "passed"
    assert evaluation["guardian"]["trust_score"] == 0.75
    assert evaluation["guardian"]["verdict"] == "trusted"
    assert evaluation["city_brain"]["action"] == "simulated_dispatch"
    assert evaluation["city_brain"]["simulated_only"] is True


def test_unconfirmed_fire_uses_correlation_penalty_and_blocks_action(client):
    response = client.post("/api/simulations/fake_fire", json={})
    evaluation = response.json()["focus_evaluation"]
    assert evaluation["layer_c"]["strength"] < 0.34
    assert evaluation["layer_c"]["status"] == "failed"
    assert "no_correlated_evidence" in evaluation["guardian"]["reasons"]
    assert evaluation["guardian"]["verdict"] == "compromised"
    assert evaluation["city_brain"]["allowed"] is False


def test_model_unavailable_does_not_create_probability_or_guardian_trust(client):
    response = client.post("/api/simulations/model_unavailable", json={})
    evaluation = response.json()["focus_evaluation"]
    assert evaluation["ml"]["status"] == "unavailable"
    assert evaluation["ml"]["probability"] is None
    assert evaluation["ml"]["error"].startswith("injected_model_unavailable")
    assert evaluation["guardian"]["trust_score"] is not None
    assert evaluation["guardian"]["scoring_breakdown"]["ml_numeric_contribution"] == 0


@pytest.mark.parametrize(("scenario_id", "body"), [
    ("normal", {}),
    ("replay", {}),
    ("invalid_signature", {}),
    ("physical_anomaly", {}),
    ("stuck_sensor", {}),
    ("adaptive_ramp", {}),
    ("corroborated_spoof", {}),
    ("custom", {"sensor_type": "water_level", "value": 65.0}),
])
def test_scenarios_complete_with_real_pipeline(client, scenario_id, body):
    response = client.post(f"/api/simulations/{scenario_id}", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["synthetic"] is True
    assert result["evaluations"]
    assert result["focus_evaluation"]["simulation_focus"] is True
    assert "processed_readings" in result["overview"]
    if scenario_id == "invalid_signature":
        assert result["overview"]["rejected_readings"] == 1


def test_stuck_health_fault_blocks_even_when_score_remains_high(client):
    response = client.post("/api/simulations/stuck_sensor", json={})
    evaluation = response.json()["focus_evaluation"]
    assert evaluation["layer_b"]["checks"]["stuck_sensor"] == "failed"
    assert evaluation["guardian"]["verdict"] == "trusted"
    assert evaluation["city_brain"]["allowed"] is False
    assert evaluation["city_brain"]["reason"] == "layer_b_hard_validation_failed"


def test_reputation_updates_follow_existing_non_trusted_verdict_policy(client):
    response = client.post("/api/simulations/fake_fire", json={})
    evaluation = response.json()["focus_evaluation"]
    change = evaluation["reputation_change"]
    assert change["raw_flags_after"] == change["raw_flags_before"] + 1
    rep = client.get(f"/reputation/{evaluation['sensor_id']}").json()
    assert rep["raw_flag_count"] == change["raw_flags_after"]


def test_unsupported_air_quality_quantity_is_unavailable_not_guessed(client):
    for seq in range(1, 7):
        client.post("/ingest", json=request_body(
            sensor_id="air-aqi", sensor_type="air_quality", value=40.0 + seq,
            unit="AQI", timestamp=1_800_000_000.0 + seq * 5, sequence_number=seq,
        ))
    response = client.post("/ingest", json=request_body(
        sensor_id="air-aqi", sensor_type="air_quality", value=47.0,
        unit="AQI", timestamp=1_800_000_030.0, sequence_number=7,
    ))
    evaluation = response.json()["evaluation"]
    assert evaluation["ml"]["status"] == "unavailable"
    assert evaluation["ml"]["probability"] is None
    assert evaluation["ml"]["error"].startswith("unsupported_quantity")


def test_malformed_readings_and_unknown_scenario_return_clear_errors(client):
    missing = request_body()
    del missing["value"]
    assert client.post("/ingest", json=missing).status_code == 422
    wrong_unit = client.post("/ingest", json=request_body(unit="volts"))
    assert wrong_unit.status_code == 422
    boolean_sequence = client.post("/ingest", json=request_body(sequence_number=True))
    assert boolean_sequence.status_code == 422
    unknown = client.post("/api/simulations/not-a-scenario", json={})
    assert unknown.status_code == 422


def test_correlated_spoof_is_visible_as_a_model_limitation_and_dashboard_uses_backend(client):
    response = client.post("/api/simulations/corroborated_spoof", json={})
    evaluation = response.json()["focus_evaluation"]
    assert evaluation["layer_c"]["strength"] == 1.0
    assert evaluation["guardian"]["verdict"] == "trusted"
    overview = client.get("/api/overview").json()
    assert overview["processed_readings"] == len(response.json()["evaluations"])
    assert overview["trusted_readings"] > 0
    assert overview["model_available"] is True
    assert client.get("/api/timeline").json()["events"]


def test_mcp_transport_remains_available_on_unified_service(client):
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "integration-test", "version": "1"},
            },
        },
        headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "Host": "127.0.0.1:5000"},
    )
    assert response.status_code == 200
