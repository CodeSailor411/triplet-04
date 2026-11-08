"""Checks for actual Compose certificate trust and timeline input boundaries."""

import json
import runpy
import ssl
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


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


def test_timeline_links_observed_events_and_does_not_duplicate_on_restart(tmp_path):
    helpers = runpy.run_path(str(SCRIPTS / "compose_timeline.py"))
    run_id = "run-42-001"
    reading_id = "rd0000012-SH-05.congestion_index"
    brain_source, guardian_source = tmp_path / "brain-input", tmp_path / "guardian-input"
    decision = {"run_id": run_id, "tick": 13, "event": "decision_made", "layer": "city_brain",
                "ts": "2026-10-05T08:00:13.000Z", "refs": {"reading_ids": [reading_id]},
                "data": {"status": "committed", "action": "set_signal_plan", "token": "excluded"}}
    verdict = {"run_id": run_id, "timestamp": 1794018962.0, "event_type": "reading_evaluated",
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
    projected = json.loads((tmp_path / f"{run_id}.brain.jsonl").read_text())
    assert projected["event_type"] == "decision" and projected["data"]["status"] == "committed"
    assert "excluded" not in json.dumps(projected)
