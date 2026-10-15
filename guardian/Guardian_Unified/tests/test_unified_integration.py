"""End-to-end checks for the Guardian + model integration boundary."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

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
