"""The legacy HTTP entry point must delegate containment to the unified Twin client."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "guardian_layer"))

import unified_api  # noqa: E402
from audit_log import JsonlAuditLog  # noqa: E402
from guardian import main as legacy_api  # noqa: E402
from guardian.reputation import ReputationStore  # noqa: E402
from integration_service import service  # noqa: E402


def test_legacy_isolate_route_calls_twin_before_mirroring_local_state(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GUARDIAN_API_BEARER_KEY", "legacy-api-key")
    monkeypatch.delenv("BRAIN_MCP_URL", raising=False)
    monkeypatch.delenv("BRAIN_GUARDIAN_CALLER_KEY", raising=False)
    service.reset()
    monkeypatch.setattr(unified_api, "_audit_log", JsonlAuditLog(tmp_path))
    monkeypatch.setattr(legacy_api, "reputation", ReputationStore())
    calls = []

    def twin(tool, arguments):
        calls.append(("twin", tool, arguments))
        return {"status": "applied", "run_id": "legacy-run", "changed": ["WAT-01.water_level"]}

    def brain(event):
        calls.append(("brain", event))
        return {"status": "accepted"}

    monkeypatch.setattr(unified_api, "call_twin_tool_sync", twin)
    monkeypatch.setattr(unified_api, "notify_containment_mcp_sync", brain)
    response = TestClient(legacy_api.app).post(
        "/isolate_sensor/WAT-01.water_level", json={"reason": "joint gate"},
        headers={"Authorization": "Bearer legacy-api-key"},
    )

    assert response.status_code == 200, response.text
    assert calls[0] == ("twin", "isolate_sensor", {
        "device_ids": ["WAT-01.water_level"], "caused_by": [], "reason": "joint gate",
    })
    assert calls[1][0] == "brain"
    assert legacy_api.reputation.is_contained("WAT-01.water_level") is True


def test_legacy_isolate_does_not_mirror_when_twin_refuses(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GUARDIAN_API_BEARER_KEY", "legacy-api-key")
    service.reset()
    monkeypatch.setattr(unified_api, "_audit_log", JsonlAuditLog(tmp_path))
    monkeypatch.setattr(legacy_api, "reputation", ReputationStore())
    calls = []
    monkeypatch.setattr(unified_api, "call_twin_tool_sync", lambda tool, args: (
        calls.append((tool, args)) or {"status": "rejected", "run_id": "legacy-run", "code": "CAP_EXCEEDED"}
    ))
    monkeypatch.setattr(unified_api, "notify_containment_mcp_sync", lambda event: calls.append(event))

    response = TestClient(legacy_api.app).post(
        "/isolate_sensor/WAT-01.water_level", headers={"Authorization": "Bearer legacy-api-key"},
    )

    assert response.status_code == 409
    assert len(calls) == 1
    assert legacy_api.reputation.is_contained("WAT-01.water_level") is False
