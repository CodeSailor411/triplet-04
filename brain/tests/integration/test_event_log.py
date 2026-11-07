import json
from datetime import datetime, timezone

from civis_brain.integration.journal import EVENT_CONTEXT, Journal

from .helpers import harness, make_case


def test_jsonl_matches_shared_shape_and_never_records_token_or_signature(tmp_path):
    journal = Journal(run_log_dir=tmp_path)
    journal.set_clock(type("Clock", (), {
        "run_id": "run-42-001", "tick": 600, "time": "2026-10-05T08:10:03Z"
    })())
    journal.append({
        "event": "decision", "scenario_id": "S01", "run_id": "run-42-001", "tick": 600,
        "status": "blocked", "reason": "reading untrusted", "reading_id": "rd-600",
        "jti": "safe-jti-1", "token": "secret-token-value",
        "token_signature": "secret-signature-value", "private_key": "private-key-value",
        "readings": [{"reading_id": "rd-600", "value": 123.4}],
    })

    path = tmp_path / "s01-run-42-001.city_brain.jsonl"
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert set(row) == {
        "ts", "tick", "run_id", "scenario", "layer", "seq", "event", "summary", "refs", "data"
    }
    assert row["ts"] == "2026-10-05T08:10:03.000Z"
    assert row["tick"] == 600 and row["run_id"] == "run-42-001" and row["scenario"] == "S01"
    assert row["layer"] == "city_brain" and row["seq"] == 1 and row["event"] == "decision_made"
    assert row["refs"] == {"reading_id": "rd-600", "jti": "safe-jti-1"}
    content = path.read_text(encoding="utf-8")
    assert all(value not in content for value in (
        "secret-token-value", "secret-signature-value", "private-key-value"
    ))
    assert "readings" not in row["data"]


def test_sequence_continues_after_journal_restart_and_separates_scenarios(tmp_path):
    for scenario in ("S01", "S01", "S02"):
        Journal(run_log_dir=tmp_path).append({
            "event": "decision", "run_id": "safe-run", "tick": 1,
            "timestamp": "2026-10-05T08:10:03Z", "scenario_id": scenario,
        })

    s01 = [json.loads(line) for line in
           (tmp_path / "s01-safe-run.city_brain.jsonl").read_text().splitlines()]
    s02 = [json.loads(line) for line in
           (tmp_path / "s02-safe-run.city_brain.jsonl").read_text().splitlines()]
    assert [row["seq"] for row in s01] == [1, 2]
    assert [row["seq"] for row in s02] == [1]


def test_unscoped_event_uses_null_scenario_and_explicit_wall_time_basis(tmp_path):
    journal = Journal(run_log_dir=tmp_path)
    journal.append({"event": "brain_service_started"})

    path = tmp_path / "shared-unscoped.city_brain.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["scenario"] is None and row["run_id"] is None and row["tick"] is None
    assert row["data"]["time_basis"] == "wall_utc"
    assert datetime.fromisoformat(row["ts"].replace("Z", "+00:00")).tzinfo == timezone.utc


async def test_peer_call_context_includes_run_tick_and_scenario(tmp_path):
    runtime, twin, _, _ = harness(make_case("S01"), tmp_path)
    batch = make_case("S01")["batches"][0]
    runtime.journal.set_clock(type("Clock", (), {
        "run_id": batch["run_id"], "tick": batch["tick"], "time": batch["time"]
    })())
    seen = []

    async def capture(name, arguments):
        seen.append(dict(EVENT_CONTEXT.get()))
        return {"status": "ok"}

    twin.call_tool = capture
    await runtime._call(twin, "test_tool", {}, scenario_id="S01")
    assert seen == [{"run_id": batch["run_id"], "tick": batch["tick"], "scenario_id": "S01"}]

    path = tmp_path / "run-logs" / f"s01-{batch['run_id']}.city_brain.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    peer_rows = [row for row in rows if row["event"] == "peer_request_sent"]
    assert peer_rows and peer_rows[-1]["scenario"] == "S01"
    assert peer_rows[-1]["run_id"] == batch["run_id"] and peer_rows[-1]["tick"] == batch["tick"]


def test_logging_error_stays_latched_after_a_later_success(tmp_path, monkeypatch):
    journal = Journal(run_log_dir=tmp_path)
    failing_write = journal._write_part

    def fail_once(event):
        monkeypatch.setattr(journal, "_write_part", failing_write)
        raise OSError("disk unavailable")

    monkeypatch.setattr(journal, "_write_part", fail_once)
    journal.append({"event": "first"})
    journal.append({"event": "second"})
    assert journal.write_error["code"] == "LOG_WRITE_FAILED"
    assert journal.logging_status["error"] == journal.write_error
