import copy
from datetime import datetime

import httpx
import pytest

from civis_brain.errors import BrainError
from civis_brain.integration.guardian_http import APPROVAL_TOOL, SCORE_TOOL, GuardianHTTPPeer
from civis_brain.integration.journal import Journal


def policy():
    return {"trust": {"score_field": "trust_score", "trusted_min": .7,
                      "risk_minimums": {"R1": .5, "R2": .7, "R3": .85},
                      "risk_values_provisional": True}}


def evidence():
    return {"run_id": "http-test", "reading_id": "r1", "device_id": "water-1",
            "node_id": "water", "sensor": "water_level", "channel": None,
            "value": 40., "unit": "cm", "tick": 1, "lat": 36.8, "lon": 10.1,
            "timestamp": "2026-10-23T08:00:01Z"}


def evaluated(row):
    return {"reading_id": row["reading_id"], "synthetic": False, "action_blocked": False,
            "layer_a": {"status": "passed"},
            "original_reading": {
                "reading_id": row["reading_id"], "sensor_id": row["device_id"],
                "sensor_type": "water_level",
                "value": row["value"], "unit": row["unit"],
                "sequence_number": row["tick"],
                "timestamp": datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp(),
                "location": {"lat": row["lat"], "lng": row["lon"]}},
            "guardian": {"reading_id": row["reading_id"], "sensor_id": row["device_id"],
                         "trust_score": .9}}


def peer_with(record):
    peer = GuardianHTTPPeer("http://127.0.0.1:5000", "test-only", policy(), allow_provisional=True)

    async def get(path):
        return {"evaluations": [record]} if path.startswith("/api/evaluations") else {}

    peer._get = get
    return peer


async def score(peer, row=None):
    row = row or evidence()
    return await peer.call_tool(SCORE_TOOL, {"run_id": row["run_id"], "tick": row["tick"],
                                           "readings": [row]})


async def test_http_verdict_uses_real_numeric_score_and_strict_cutoff():
    peer = peer_with(evaluated(evidence()))
    assert (await score(peer))["scores"] == [{"reading_id": "r1", "score": .9}]
    cap = await peer.call_tool("get_capabilities", {})
    assert cap["thresholds"]["reading"] > .7
    assert cap["authorization_ready"] is False


@pytest.mark.parametrize("field,value", [("value", 41.), ("unit", "m"),
                                        ("sequence_number", 2), ("timestamp", 0),
                                        ("sensor_id", "other"), ("location", {})])
async def test_same_id_with_different_original_content_is_not_trusted(field, value):
    record = evaluated(evidence())
    record["original_reading"][field] = value
    with pytest.raises(BrainError) as raised:
        await score(peer_with(record))
    assert raised.value.code == "GUARDIAN_EVIDENCE_MISMATCH"


@pytest.mark.parametrize("change", ["synthetic", "hard_gate", "replay", "no_verdict", "nan"])
async def test_advisory_or_rejected_evidence_cannot_become_approval(change):
    record = evaluated(evidence())
    if change == "synthetic":
        record["synthetic"] = True
    elif change == "hard_gate":
        record["action_blocked"] = True
    elif change == "replay":
        record["layer_a"]["status"] = "failed"
    elif change == "no_verdict":
        record["guardian"] = None
    else:
        record["guardian"]["trust_score"] = float("nan")
    with pytest.raises(BrainError):
        await score(peer_with(record))


async def test_run_reset_requires_a_fresh_guardian_instance():
    peer = peer_with(evaluated(evidence()))
    await score(peer)
    row = {**evidence(), "run_id": "other-run"}
    with pytest.raises(BrainError) as raised:
        await score(peer, row)
    assert raised.value.code == "GUARDIAN_RUN_RESET_REQUIRED"


async def test_bounded_window_missing_evidence_is_explicit():
    peer = peer_with({"reading_id": "other"})
    with pytest.raises(BrainError) as raised:
        await score(peer)
    assert raised.value.code == "GUARDIAN_EVIDENCE_UNAVAILABLE"


async def test_current_g1_approval_contract_never_sends_unbound_action():
    peer = peer_with(evaluated(evidence()))
    with pytest.raises(BrainError) as raised:
        await peer.call_tool(APPROVAL_TOOL, {})
    assert raised.value.code == "GUARDIAN_TOKEN_CONTRACT_UNSUPPORTED"


def test_provisional_policy_requires_explicit_mock_profile():
    with pytest.raises(ValueError, match="Provisional"):
        GuardianHTTPPeer("http://127.0.0.1", "test-only", policy())
    bad = copy.deepcopy(policy())
    bad["trust"]["trusted_min"] = float("nan")
    with pytest.raises(ValueError):
        GuardianHTTPPeer("http://127.0.0.1", "test-only", bad, allow_provisional=True)


def test_g1_tokens_are_redacted_even_in_free_text():
    assert Journal().redact("Rejected g1.eyJmb28iOjF9.c2lnbmF0dXJl") == "Rejected <redacted>"


@pytest.mark.parametrize("status,expected", [(401, "GUARDIAN_UNAUTHENTICATED"),
    (403, "GUARDIAN_UNAUTHENTICATED"), (503, "GUARDIAN_HTTP_ERROR"),
    (302, "GUARDIAN_HTTP_ERROR")])
async def test_http_auth_errors_and_redirects_fail_closed(monkeypatch, status, expected):
    original = httpx.AsyncClient

    def handler(request):
        assert request.headers["authorization"] == "Bearer test-only"
        return httpx.Response(status, json={"detail": "not public"})

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    peer = GuardianHTTPPeer("http://127.0.0.1", "test-only", policy(), allow_provisional=True)
    with pytest.raises(BrainError) as raised:
        await peer.call_tool("get_capabilities", {})
    assert raised.value.code == expected
