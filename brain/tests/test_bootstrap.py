from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from civis_brain.app import create_app
from civis_brain.contracts import ActionProposal, Reading
from civis_brain.settings import Settings


def test_service_is_honestly_not_ready():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/health").json()["ready"] is False


def test_partner_sdk_is_pinned():
    assert version("mcp") == "2.3.0"


def test_null_is_preserved_and_extra_peer_fields_are_ignored():
    reading = Reading.model_validate({
        "run_id": "run-demo", "reading_id": "r-1", "tick": 1,
        "timestamp": "2026-10-07T08:00:01.000Z", "node_id": "WAT-01",
        "device_id": "WAT-01.water_level", "sensor": "water_level", "channel": None,
        "value": None, "unit": "cm", "extra_partner_field": "ignored",
    })
    assert reading.value is None
    assert "extra_partner_field" not in reading.model_dump()


def test_ai_cannot_add_a_token_to_a_proposal():
    with pytest.raises(ValidationError):
        ActionProposal.model_validate({
            "action": "dispatch", "targets": ["EMG-07"],
            "params": {"unit_type": "ambulance", "destination": "EMG-01", "units": 1},
            "risk": "R2", "preview_required": False, "source_reading_ids": ["r-1"],
            "reason": "Reported medical incident", "token": "invented-by-model",
        })
