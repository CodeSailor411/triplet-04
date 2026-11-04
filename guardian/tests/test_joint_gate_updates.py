"""Guardian regressions for the clarified Twin twin-mock-3 joint gate."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import unified_api  # noqa: E402
from audit_log import JsonlAuditLog  # noqa: E402
from brain_client import BrainDeliveryError, _containment_tool_arguments  # noqa: E402
from integration_service import service  # noqa: E402
from token_service import ActionTokenService  # noqa: E402
from twin_adapter import normalize_twin_reading  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # These route tests do not use Guardian MCP; avoid consuming its single-run
    # lifespan so the suite's real MCP transport test can start it later.
    return TestClient(unified_api.app)


@pytest.fixture(autouse=True)
def reset_guardian(monkeypatch, tmp_path):
    service.reset()
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GUARDIAN_API_BEARER_KEY", "joint-gate-key")
    for name in ("TWIN_BASE_URL", "GUARDIAN_TWIN_BEARER_KEY", "BRAIN_MCP_URL",
                 "GUARDIAN_BRAIN_BEARER_KEY", "BRAIN_VERDICT_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(unified_api, "_audit_log", JsonlAuditLog(tmp_path))
    monkeypatch.setattr(unified_api, "_token_service", ActionTokenService(
        private_key=Ed25519PrivateKey.generate(), clock=lambda: 1_800_000_000.0))
    monkeypatch.setattr(unified_api, "_refresh_twin_sim_clock", lambda: 1_800_000_000.0)
    monkeypatch.setattr(unified_api, "_fresh_verdict", lambda reading_id: service.verdict_log[reading_id])
    unified_api._latest_twin_run_id = None
    unified_api._latest_twin_sim_time = None
    unified_api._twin_discovery_by_run.clear()
    unified_api._twin_delivery_cache.clear()
    unified_api._last_tick_by_run.clear()
    yield
    service.reset()
    unified_api._latest_twin_run_id = None
    unified_api._twin_discovery_by_run.clear()
    unified_api._twin_delivery_cache.clear()
    unified_api._last_tick_by_run.clear()


def _manifest(actions: list[dict], *, preview_enforced: bool = False) -> dict:
    return {
        "list_actions": {"actions": actions, "preview_enforced": preview_enforced},
        "get_clock": {"run_id": "gate-run", "simulated_time": 1_800_000_000.0},
        "list_nodes": {"nodes": []},
        "get_containment_state": {"quarantined": []},
    }


def _install_manifest(monkeypatch, manifest: dict) -> None:
    monkeypatch.setattr(unified_api, "_ensure_twin_discovery", lambda _run_id: manifest)


def _ingest(client: TestClient, readings: list[dict], run_id: str = "gate-run") -> dict:
    response = client.post("/api/integrations/twin/event", json={
        "event": "readings", "data": {"run_id": run_id, "readings": readings},
    }, headers={"Authorization": "Bearer joint-gate-key"})
    assert response.status_code == 200, response.text
    assert response.json()["skipped"] == []
    return response.json()


def _trusted(*reading_ids: str) -> None:
    for reading_id in reading_ids:
        verdict = service.verdict_log[reading_id]
        verdict.trust_score = 1.0
        verdict.verdict = "trusted"


def _reading(*, reading_id: str, device_id: str, node_id: str, sensor: str,
             value: float, unit: str, tick: int = 1, channel: str | None = None) -> dict:
    return {
        "run_id": "gate-run", "reading_id": reading_id, "device_id": device_id,
        "timestamp": 1_800_000_000 + tick, "tick": tick, "node_id": node_id,
        "sensor": sensor, "channel": channel, "value": value, "unit": unit,
        "lat": 36.8, "lon": 10.1,
    }


def _authorize(client: TestClient, *, reading_id: str, reading_ids: list[str], action: str,
               parameters: dict, targets: list[str], risk: str, domain: str,
               idempotency_key: str = "gate-key"):
    return client.post("/api/actions/authorize", json={
        "run_id": "gate-run", "reading_id": reading_id, "reading_ids": reading_ids,
        "action": action, "parameters": parameters, "targets": targets,
        "idempotency_key": idempotency_key, "risk_level": risk, "domain": domain,
    }, headers={"Authorization": "Bearer joint-gate-key"})


def test_units_free_channels_are_independent_and_scored(client):
    ambulance = _reading(reading_id="units-ambulance-1", device_id="EMG-07.units_free",
        node_id="EMG-07", sensor="units_free", channel="ambulance", value=5, unit="units")
    police = {**ambulance, "reading_id": "units-police-1", "channel": "police", "value": 6}
    normalized = normalize_twin_reading(ambulance)
    assert normalized["channel"] == "ambulance"
    assert normalized["node_id"] == "EMG-07"
    assert normalized["sensor_id"] != normalize_twin_reading(police)["sensor_id"]

    result = _ingest(client, [ambulance, police])
    assert result["processed"] == 2
    evaluations = [item["evaluation"] for item in result["results"]]
    assert all(item["sensor_type"] == "units_free" for item in evaluations)
    assert all(item["domain"] == "emergency" for item in evaluations)
    assert all(item["guardian"]["trust_score"] == 1.0 for item in evaluations)
    assert all(item["ml"]["status"] == "unavailable" for item in evaluations)
    assert evaluations[0]["original_reading"]["channel"] == "ambulance"
    assert evaluations[0]["original_reading"]["device_id"] == "EMG-07.units_free"


def test_s02_authorizes_only_the_exact_preview_gated_valve_command(client, monkeypatch):
    manifest = _manifest([{
        "action": "set_valve_position", "domain": "Water", "risk": "R3",
        "preview_required": True, "target_nodes": ["WAT-01"],
    }], preview_enforced=True)
    _install_manifest(monkeypatch, manifest)
    _ingest(client, [_reading(reading_id="s02-water", device_id="WAT-01.water_level",
        node_id="WAT-01", sensor="water_level", value=80, unit="cm")])
    _trusted("s02-water")
    response = _authorize(client, reading_id="s02-water", reading_ids=["s02-water"],
        action="set_valve_position", parameters={"position": 40}, targets=["WAT-01"],
        risk="R3", domain="Water")
    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "approved"


@pytest.mark.parametrize(("parameters", "targets", "preview_enforced", "status", "expected"), [
    ({"position": 39}, ["WAT-01"], True, 403, "twin_action_contract_mismatch"),
    ({"position": 40}, ["WAT-02"], True, 403, "target_not_in_twin_manifest"),
    ({"position": 40}, ["WAT-01"], False, 409, "safe_preview_tool_unconfirmed"),
])
def test_s02_rejects_noncontract_command_or_unenforced_preview(
    client, monkeypatch, parameters, targets, preview_enforced, status, expected,
):
    manifest = _manifest([{
        "action": "set_valve_position", "domain": "Water", "risk": "R3",
        "preview_required": True, "target_nodes": ["WAT-01", "WAT-02"],
    }], preview_enforced=preview_enforced)
    _install_manifest(monkeypatch, manifest)
    _ingest(client, [_reading(reading_id="s02-water", device_id="WAT-01.water_level",
        node_id="WAT-01", sensor="water_level", value=80, unit="cm")])
    _trusted("s02-water")
    response = _authorize(client, reading_id="s02-water", reading_ids=["s02-water"],
        action="set_valve_position", parameters=parameters, targets=targets,
        risk="R3", domain="Water")
    assert response.status_code == status
    assert response.json()["detail"] == expected


def _dispatch_evidence() -> list[dict]:
    return [
        _reading(reading_id="medical-incident-1", device_id="CALL-01.emergency_calls",
            node_id="CALL-01", sensor="emergency_calls", channel="medical",
            value=12, unit="calls/min"),
        _reading(reading_id="ambulance-capacity-1", device_id="EMG-01.units_free",
            node_id="EMG-01", sensor="units_free", channel="ambulance",
            value=5, unit="units"),
    ]


def test_s05_binds_medical_and_current_ambulance_capacity_readings(client, monkeypatch):
    carrier = "EMG-01"
    manifest = _manifest([{
        "action": "dispatch", "domain": "Emergency", "risk": "R2",
        "preview_required": False, "target_nodes": [carrier],
    }])
    _install_manifest(monkeypatch, manifest)
    calls = []

    def get_current(name, arguments):
        calls.append((name, arguments))
        return {"run_id": "gate-run", "readings": [{
            "reading_id": "ambulance-capacity-1", "node_id": carrier,
            "sensor": "units_free", "channel": "ambulance", "value": 5, "unit": "units",
        }]}

    monkeypatch.setattr(unified_api, "call_twin_tool_sync", get_current)
    _ingest(client, _dispatch_evidence())
    _trusted("medical-incident-1", "ambulance-capacity-1")
    response = _authorize(client, reading_id="medical-incident-1",
        reading_ids=["medical-incident-1", "ambulance-capacity-1"], action="dispatch",
        parameters={"unit_type": "ambulance", "destination": "CALL-01", "units": 1},
        targets=[carrier], risk="R2", domain="Emergency")

    assert response.status_code == 200, response.text
    assert calls == [("get_readings", {"node_id": carrier, "sensor": "units_free"})]
    claims = unified_api._token_service.verify(response.json()["token"], action="dispatch",
        parameters={"unit_type": "ambulance", "destination": "CALL-01", "units": 1},
        targets=[carrier], idempotency_key="gate-key", consume=False)
    assert claims["reading_ids"] == ["medical-incident-1", "ambulance-capacity-1"]


def test_s05_rejects_stale_capacity_reading_and_multiple_units(client, monkeypatch):
    carrier = "EMG-01"
    _install_manifest(monkeypatch, _manifest([{
        "action": "dispatch", "domain": "Emergency", "risk": "R2",
        "preview_required": False, "target_nodes": [carrier],
    }]))
    monkeypatch.setattr(unified_api, "call_twin_tool_sync", lambda *_: {
        "run_id": "gate-run", "readings": [{
            "reading_id": "new-capacity-reading", "node_id": carrier,
            "sensor": "units_free", "channel": "ambulance", "value": 5, "unit": "units",
        }],
    })
    _ingest(client, _dispatch_evidence())
    _trusted("medical-incident-1", "ambulance-capacity-1")
    common = dict(reading_id="medical-incident-1",
        reading_ids=["medical-incident-1", "ambulance-capacity-1"], action="dispatch",
        targets=[carrier], risk="R2", domain="Emergency")
    stale = _authorize(client, parameters={"unit_type": "ambulance", "destination": "CALL-01", "units": 1}, **common)
    multiple = _authorize(client, parameters={"unit_type": "ambulance", "destination": "CALL-01", "units": 2}, **common)
    assert stale.status_code == 409
    assert stale.json()["detail"] == "ambulance_capacity_evidence_not_current"
    assert multiple.status_code == 403
    assert multiple.json()["detail"] == "invalid_dispatch_units"


def test_rollback_calls_twin_then_brain_and_invalidates_trust(client, monkeypatch):
    calls = []

    def twin(tool, arguments):
        calls.append(("twin", tool, arguments))
        return {"status": "applied", "run_id": "gate-run", "corrections": [
            {"device_id": "WAT-01.water_level", "corrects": "rollback-reading"},
        ]}

    def brain(event):
        calls.append(("brain", event))
        return {"status": "accepted"}

    monkeypatch.setattr(unified_api, "call_twin_tool_sync", twin)
    monkeypatch.setattr(unified_api, "notify_containment_mcp_sync", brain)
    _ingest(client, [_reading(reading_id="rollback-reading", device_id="WAT-01.water_level",
        node_id="WAT-01", sensor="water_level", value=80, unit="cm")])
    response = client.post("/rollback_reading", json={
        "reading_ids": ["rollback-reading"], "caused_by": ["review-flag"],
    }, headers={"Authorization": "Bearer joint-gate-key"})
    denied = _authorize(client, reading_id="rollback-reading", reading_ids=["rollback-reading"],
        action="set_signal_plan", parameters={"plan": "normal"}, targets=["TRF-01"],
        risk="R1", domain="Traffic")

    assert response.status_code == 200, response.text
    assert [call[0] for call in calls] == ["twin", "brain"]
    assert calls[0] == ("twin", "rollback_reading", {
        "reading_ids": ["rollback-reading"], "caused_by": ["review-flag"],
    })
    assert calls[1][1]["tool"] == "rollback_reading"
    assert calls[1][1]["reading_ids"] == ["rollback-reading"]
    assert service.buffer.is_invalid("rollback-reading")
    assert "rollback-reading" not in service.verdict_log
    assert denied.status_code == 409
    assert denied.json()["detail"] == "reading_invalidated"


def test_rejected_twin_containment_does_not_change_local_state_or_notify_brain(client, monkeypatch):
    calls = []
    monkeypatch.setattr(unified_api, "call_twin_tool_sync", lambda tool, args: (
        calls.append((tool, args)) or {"status": "rejected", "code": "CAP_EXCEEDED"}))
    monkeypatch.setattr(unified_api, "notify_containment_mcp_sync", lambda event: calls.append(event))
    response = client.post("/isolate_sensor/WAT-01.water_level", json={"reason": "review"},
        headers={"Authorization": "Bearer joint-gate-key"})
    assert response.status_code == 409
    assert len(calls) == 1
    assert service.reputation.is_contained("WAT-01.water_level") is False


def test_authorization_reads_twin_quarantine_device_state(client, monkeypatch):
    _install_manifest(monkeypatch, {
        **_manifest([{
            "action": "set_signal_plan", "domain": "Traffic", "risk": "R1",
            "preview_required": False, "target_nodes": ["TRF-01"],
        }]),
        "get_containment_state": {"devices": [{
            "device_id": "TRF-01.congestion_index", "node_id": "TRF-01", "state": "quarantined",
        }]},
    })
    _ingest(client, [_reading(reading_id="quarantine-evidence", device_id="TRF-01.congestion_index",
        node_id="TRF-01", sensor="congestion_index", value=35, unit="percent")])
    _trusted("quarantine-evidence")
    response = _authorize(client, reading_id="quarantine-evidence",
        reading_ids=["quarantine-evidence"], action="set_signal_plan",
        parameters={"plan": "normal"}, targets=["TRF-01"], risk="R1", domain="Traffic")
    assert response.status_code == 409
    assert response.json()["detail"] == "DEVICE_QUARANTINED"


def test_action_token_signature_is_required_and_verified(client, monkeypatch):
    _install_manifest(monkeypatch, _manifest([{
        "action": "set_signal_plan", "domain": "Traffic", "risk": "R1",
        "preview_required": False, "target_nodes": ["TRF-01"],
    }]))
    _ingest(client, [_reading(reading_id="signed-action-evidence", device_id="TRF-01.congestion_index",
        node_id="TRF-01", sensor="congestion_index", value=35, unit="percent")])
    _trusted("signed-action-evidence")
    issued = _authorize(client, reading_id="signed-action-evidence",
        reading_ids=["signed-action-evidence"], action="set_signal_plan",
        parameters={"plan": "normal"}, targets=["TRF-01"], risk="R1", domain="Traffic")
    token = issued.json()["token"]
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}." + "A" * 86
    verify_body = {"token": tampered, "action": "set_signal_plan",
        "parameters": {"plan": "normal"}, "targets": ["TRF-01"], "idempotency_key": "gate-key"}
    rejected = client.post("/api/actions/verify", json=verify_body,
        headers={"Authorization": "Bearer joint-gate-key"})
    verify_body["token"] = token
    accepted = client.post("/api/actions/verify", json=verify_body,
        headers={"Authorization": "Bearer joint-gate-key"})
    assert issued.status_code == 200
    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["verified"] is True


def test_brain_notify_schema_mapping_requires_a_supported_payload_field():
    event = {"event_id": "event-1", "run_id": "gate-run", "tool": "rollback_reading",
        "status": "applied", "reading_ids": ["reading-1"], "device_ids": [],
        "caused_by": ["flag-1"], "twin_result": {"status": "applied"}}
    args = _containment_tool_arguments({"properties": {
        "event_id": {"type": "string"}, "operation": {"type": "string"},
        "reading_ids": {"type": "array"}, "result": {"type": "object"},
    }, "required": ["event_id", "operation", "reading_ids", "result"]}, event)
    assert args == {"event_id": "event-1", "operation": "rollback_reading",
        "reading_ids": ["reading-1"], "result": {"status": "applied"}}
    with pytest.raises(BrainDeliveryError, match="unsupported fields"):
        _containment_tool_arguments({"properties": {"unmapped": {"type": "string"}},
            "required": ["unmapped"]}, event)
