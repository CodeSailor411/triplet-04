"""Checks for actual Compose certificate trust and timeline input boundaries."""

import io
import json
import runpy
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civis_brain.app import create_app
from civis_brain.settings import Settings

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def test_dashboard_timeout_still_runs_backend_checks(tmp_path, monkeypatch, capsys):
    launcher = runpy.run_path(str(SCRIPTS / "compose_stack.py"))
    main = launcher["main"]
    monkeypatch.setitem(main.__globals__, "BRAIN", tmp_path)
    monkeypatch.setitem(main.__globals__, "prepare_stack", lambda: tmp_path)
    (tmp_path / ".env.compose").touch()
    monkeypatch.setattr(sys, "argv", ["compose_stack.py", "check"])
    monkeypatch.setattr(ssl, "create_default_context", lambda **_: None)
    commands = []

    def run(command, **_):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="test certificate")

    def urlopen(url, **_):
        if url.endswith(":8080/"):
            raise TimeoutError("timed out")
        response = io.StringIO('{"run_id": "run-42-002", "tick": 16}')
        response.status = 200
        return response

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
    assert commands[-1][-5:-1] == ["-T", "brain", "python", "-c"]
    output = capsys.readouterr().out
    assert "Trinity dashboard http://127.0.0.1:8080/ -> timed out" in output
    assert '"run_id": "run-42-002", "twin_clock": 16' in output


def test_compose_tls_identity_is_trusted_and_reused(tmp_path):
    ensure_tls = runpy.run_path(str(SCRIPTS / "compose_tls.py"))["ensure_tls"]
    key, cert = tmp_path / "private" / "brain.key", tmp_path / "public" / "brain.crt"
    ensure_tls(key, cert)
    old_cert = cert.read_bytes()
    ensure_tls(key, cert)
    assert cert.read_bytes() == old_cert
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    client_context = ssl.create_default_context(cafile=str(cert))
    to_server, to_client = ssl.MemoryBIO(), ssl.MemoryBIO()
    client = client_context.wrap_bio(to_client, to_server, server_hostname="brain")
    server = server_context.wrap_bio(to_server, to_client, server_side=True)
    client_done = server_done = False
    for _ in range(10):
        try:
            client.do_handshake()
            client_done = True
        except ssl.SSLWantReadError:
            pass
        try:
            server.do_handshake()
            server_done = True
        except ssl.SSLWantReadError:
            pass
        if client_done and server_done:
            break
    assert client_done and server_done


def test_brain_mcp_accepts_configured_compose_host_and_rejects_unknown_hosts():
    settings = Settings(_env_file=None, brain_mcp_allowed_hosts=["brain:8001"])
    initialize = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                   "clientInfo": {"name": "compose-check", "version": "1"}},
    }
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(create_app(settings), base_url="https://brain:8001") as client:
        assert client.post("/mcp", json=initialize, headers=headers).status_code == 200
        assert client.post("/mcp", json=initialize, headers={
            **headers, "Host": "unknown:8001",
        }).status_code == 421
        assert client.post("/mcp", json=initialize, headers={
            **headers, "Origin": "https://unknown",
        }).status_code == 403


@pytest.mark.parametrize("clock", [
    {"timestamp": 1794018962.0},
    {"timestamp": "2026-10-05T08:00:12Z", "wall": "2026-11-07T04:00:00Z"},
])
def test_timeline_links_observed_events_and_does_not_duplicate_on_restart(tmp_path, clock):
    helpers = runpy.run_path(str(SCRIPTS / "compose_timeline.py"))
    run_id = "run-42-001"
    reading_id = "rd0000012-SH-05.congestion_index"
    brain_source, guardian_source = tmp_path / "brain-input", tmp_path / "guardian-input"
    decision = {"run_id": run_id, "tick": 13, "event": "decision_made", "layer": "city_brain",
                "ts": "2026-10-05T08:00:13.000Z", "refs": {"reading_ids": [reading_id]},
                "data": {"status": "committed", "action": "set_signal_plan", "token": "excluded"}}
    verdict = {"run_id": run_id, **clock, "event_type": "reading_evaluated",
               "trust_score": 1.0, "reading_id": reading_id, "verdict": "trusted",
               "data": {"sequence_number": 12, "sensor_id": "SH-05.congestion_index"}}
    authorization = {**verdict, "event_type": "action_decision", "decision": "approved",
                     "requested_action": "set_signal_plan", "data": {"token_id": "opaque-id"}}
    brain_source.write_text(json.dumps(decision) + "\n", encoding="utf-8")
    guardian_source.write_text(json.dumps(verdict) + "\n" + json.dumps(authorization),
                               encoding="utf-8")
    timeline = helpers["Timeline"](tmp_path)
    timeline.poll(brain_source, helpers["brain_event"])
    timeline.poll(guardian_source, timeline.guardian_event)
    guardian_part = tmp_path / f"{run_id}.guardian.jsonl"
    assert len(guardian_part.read_text().splitlines()) == 1
    with guardian_source.open("a", encoding="utf-8") as stream:
        stream.write("\n")
    timeline.poll(guardian_source, timeline.guardian_event)
    restarted = helpers["Timeline"](tmp_path)
    restarted.poll(brain_source, helpers["brain_event"])
    restarted.poll(guardian_source, restarted.guardian_event)
    rows = [json.loads(line) for line in guardian_part.read_text().splitlines()]
    assert len(rows) == 2 and all(row["tick"] == 12 for row in rows)
    assert rows[1]["data"]["token_id"] == "opaque-id"
    assert rows[0]["caused_by"] == [reading_id]
    assert rows[0]["event_id"].startswith("guardian-")
    assert "T" in rows[0]["wall"]
    if "wall" in clock:
        assert rows[0]["timestamp"] == clock["timestamp"]
        assert rows[0]["wall"] == clock["wall"]
    projected = json.loads((tmp_path / f"{run_id}.brain.jsonl").read_text())
    assert projected["event_type"] == "decision" and projected["data"]["status"] == "committed"
    assert projected["event_id"].startswith("brain-")
    assert "excluded" not in json.dumps(projected)


def test_timeline_shows_twin_feed_receipts_and_keeps_real_brain_blocks(tmp_path):
    helpers = runpy.run_path(str(SCRIPTS / "compose_timeline.py"))
    run_id = "run-42-001"
    reading_ids = ["rd0000217-SH-05.congestion_index", "rd0000217-POW-01.load_kw"]
    shared = {"run_id": run_id, "tick": 217, "layer": "city_brain",
              "ts": "2026-10-05T08:03:37Z", "refs": {"reading_ids": reading_ids}}
    batch = {**shared, "event": "readings_batch_received", "data": {"count": 2}}
    warning = {**shared, "event": "decision_made", "scenario": "S03",
               "data": {"status": "alert", "peer_code": "EVIDENCE_WARNING",
                        "reason": "POWER_EVIDENCE_UNCONFIRMED: no agreed fault threshold"}}
    block = {**shared, "event": "decision_made", "scenario": "S01",
             "data": {"status": "blocked", "peer_code": "TRUST_BELOW_THRESHOLD"}}
    source = tmp_path / "brain-input"
    raw = "".join(json.dumps(row) + "\n" for row in (batch, warning, block))
    source.write_text(raw, encoding="utf-8")
    for _ in range(2):
        helpers["Timeline"](tmp_path).poll(source, helpers["brain_event"])
    reading = json.loads((tmp_path / f"{run_id}.twin.jsonl").read_text())
    assert reading["tick"] == 217 and reading["layer"] == "twin" and reading["event_type"] == "reading"
    assert reading["event_id"].startswith("twin-feed-")
    assert reading["data"]["reading_ids"] == reading_ids and reading["data"]["value"] == 2
    decision = json.loads((tmp_path / f"{run_id}.brain.jsonl").read_text())
    assert decision["data"]["incident"] == "S01 blocked (TRUST_BELOW_THRESHOLD)"
    assert decision["caused_by"] == reading_ids
    assert source.read_text() == raw
