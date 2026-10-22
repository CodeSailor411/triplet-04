"""Local-only tests for outbound Guardian verdict delivery."""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brain_client import BrainDeliveryError, VerdictOutbox, post_verdict, verdict_payload  # noqa: E402


def _evaluation():
    return {
        "reading_id": "reading-1",
        "sensor_id": "power-sensor-1",
        "timestamp": 1800000000,
        "original_reading": {"value": 450, "location": {"lat": 1, "lng": 2}},
        "guardian": {"verdict": "trusted", "trust_score": 0.91, "reasons": []},
        "city_brain": {"status": "allowed", "allowed": True, "action": "consume_reading",
                       "reason": "policy_satisfied", "simulated_only": True},
        "ml": {"label": "Trusted", "probability": 0.03, "model_version": "test", "advisory_only": True},
    }


def _server(handler_type):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_type)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_verdict_payload_is_stable_and_excludes_raw_reading_data():
    first = verdict_payload("run-1", _evaluation())
    second = verdict_payload("run-1", _evaluation())
    assert first == second
    assert first["schema_version"] == "guardian.verdict.v1"
    assert first["verdict"] == "trusted"
    assert first["trust_score"] == .91
    assert first["city_brain"]["simulated_only"] is True
    assert first["model_advisory"]["advisory_only"] is True
    assert "original_reading" not in first
    assert "event_id" in first
    assert verdict_payload("run-1", {"guardian": None}) is None


def test_outbox_recovers_pending_and_removes_delivered_records(tmp_path):
    path = tmp_path / "brain-outbox.jsonl"
    payload = verdict_payload("run-1", _evaluation())
    outbox = VerdictOutbox(path)
    outbox.enqueue(payload)
    outbox.enqueue(payload)
    assert len(outbox.pending()) == 1

    recovered = VerdictOutbox(path)
    assert recovered.pending() == [payload]
    recovered.mark_delivered(payload["event_id"])
    assert VerdictOutbox(path).pending() == []


def test_post_verdict_sends_bearer_idempotency_and_json():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received.append({
                "authorization": self.headers.get("Authorization"),
                "idempotency_key": self.headers.get("Idempotency-Key"),
                "body": json.loads(self.rfile.read(length)),
            })
            self.send_response(202)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server, thread = _server(Handler)
    try:
        payload = verdict_payload("run-1", _evaluation())
        status = post_verdict(payload, url=f"http://127.0.0.1:{server.server_port}/verdicts",
                              bearer_key="brain-test-key", max_retries=0)
        assert status == 202
        assert received == [{"authorization": "Bearer brain-test-key",
                             "idempotency_key": payload["event_id"], "body": payload}]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_post_verdict_retries_transient_brain_error(monkeypatch):
    attempts = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            attempts.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(503 if len(attempts) == 1 else 204)
            self.end_headers()

        def log_message(self, *_args):
            pass

    monkeypatch.setattr("brain_client.time.sleep", lambda _delay: None)
    server, thread = _server(Handler)
    try:
        payload = verdict_payload("run-1", _evaluation())
        status = post_verdict(payload, url=f"http://127.0.0.1:{server.server_port}/verdicts",
                              bearer_key="brain-test-key", max_retries=1, retry_base_seconds=0)
        assert status == 204
        assert len(attempts) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_post_verdict_does_not_retry_auth_failure():
    attempts = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            attempts.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(401)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server, thread = _server(Handler)
    try:
        payload = verdict_payload("run-1", _evaluation())
        with pytest.raises(BrainDeliveryError, match="HTTP 401"):
            post_verdict(payload, url=f"http://127.0.0.1:{server.server_port}/verdicts",
                         bearer_key="wrong-key", max_retries=3)
        assert len(attempts) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
