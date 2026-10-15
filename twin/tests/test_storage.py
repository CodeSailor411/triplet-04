"""History storage (13 Oct): the interface, the background writer, and PostgreSQL / TimescaleDB.

The PostgreSQL tests need a database. They run only when TWIN_TEST_PG_DSN is set, for example
  TWIN_TEST_PG_DSN=postgresql://twin:twinpw@127.0.0.1:5432/twin_test python -m pytest tests/test_storage.py
Without it they are skipped (and say so), so a plain `pytest` works on any machine.
"""
import asyncio
import json
import os

import pytest

from test_runlog import build, run
from twin.app import follow_history
from twin.generator import generate
from twin.settings import StorageCfg, load_config
from twin.sim import Simulation
from twin.storage import HistoryWriter, MemoryHistory, open_history

PG_DSN = os.environ.get("TWIN_TEST_PG_DSN")
needs_pg = pytest.mark.skipif(not PG_DSN, reason="set TWIN_TEST_PG_DSN to run the PostgreSQL tests")


def make_sim():
    cfg = load_config()
    topo, _ = generate(cfg)
    return Simulation(topo, cfg)


def reading_rows(sim, tick):
    return [r.model_dump() for r in sim.readings_at(tick).readings]


def event_line(n, run_id="run-42-001", **data):
    return {"run_id": run_id, "event_id": f"twin-{n:06d}", "timestamp": "2026-10-05T08:00:00.000Z", "tick": n,
            "wall": "2026-10-12T10:00:00.000Z", "layer": "twin", "event_type": "action", "caused_by": [], "data": data}


# ------------------------------------------------------------------ memory backend and the choice of backend
def test_memory_store_skips_rows_it_already_has():
    sim, store = make_sim(), MemoryHistory()
    rows = reading_rows(sim, 5)
    store.write_readings(rows)
    store.write_readings(rows)                                   # a retry: no duplicates
    assert len(store.query_readings(sim.run_id)) == len(rows) > 60


def test_memory_store_filters_by_device_and_tick():
    sim, store = make_sim(), MemoryHistory()
    for t in range(10):
        store.write_readings(reading_rows(sim, t))
    got = store.query_readings(sim.run_id, device_id="WAT-01.water_level", from_tick=3, to_tick=6)
    assert [r["tick"] for r in got] == [3, 4, 5, 6]


def test_default_config_is_memory_and_needs_nothing_installed():
    assert load_config().storage.history == "memory"
    assert open_history(load_config().storage).store.name == "memory"


def test_timescale_without_a_connection_string_stops_with_a_clear_message():
    cfg = StorageCfg(history="timescale")
    with pytest.raises(SystemExit) as e:
        open_history(cfg, environ={})
    assert "TWIN_TIMESCALE_DSN" in str(e.value)


def test_connection_string_is_read_from_the_env_file_when_the_environment_has_none(tmp_path, monkeypatch):
    monkeypatch.delenv("TWIN_TIMESCALE_DSN", raising=False)
    env = tmp_path / ".env"
    env.write_text("TWIN_TIMESCALE_DSN=postgresql://u:p@127.0.0.1:1/x\n")
    w = open_history(StorageCfg(history="timescale"), env_file=env)         # no database at that address: still opens
    assert w.store.name == "timescale" and w.store._dsn == "postgresql://u:p@127.0.0.1:1/x"
    monkeypatch.setenv("TWIN_TIMESCALE_DSN", "postgresql://real-env/wins")
    assert open_history(StorageCfg(history="timescale"), env_file=env).store._dsn == "postgresql://real-env/wins"


def test_unknown_backend_name_is_refused_by_config():
    with pytest.raises(Exception):
        StorageCfg(history="mongo")


# ------------------------------------------------------------------ the writer, with a fake store we can break
class FlakyStore(MemoryHistory):
    name = "flaky"

    def __init__(self, fail_times=0):
        super().__init__()
        self.fail_times, self.calls = fail_times, 0

    def _maybe_fail(self):
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("database is down")

    def write_readings(self, rows):
        self._maybe_fail()
        super().write_readings(rows)


def test_writer_submit_never_raises_and_flush_stores_everything():
    sim, store = make_sim(), MemoryHistory()
    w = HistoryWriter(store)
    w.submit_readings(reading_rows(sim, 1))
    w.submit_event(event_line(1))
    assert w.queued() > 60
    assert w.flush_once() is True
    assert len(store.query_readings(sim.run_id)) > 60 and len(store.query_events("run-42-001")) == 1
    assert w.queued() == 0 and w.healthy and w.written > 60


def test_writer_keeps_rows_while_the_store_fails_and_retries_in_the_same_order():
    sim, store = make_sim(), FlakyStore(fail_times=2)
    w = HistoryWriter(store)
    w.submit_readings(reading_rows(sim, 1))
    w.submit_readings(reading_rows(sim, 2))
    n = w.queued()
    assert w.flush_once() is False and w.healthy is False and w.queued() == n      # nothing lost
    assert w.flush_once() is False and w.failures == 2
    assert w.flush_once() is True and w.healthy is True and w.queued() == 0         # the database "came back"
    got = store.query_readings(sim.run_id)
    assert len(got) == n and [r["tick"] for r in got] == sorted(r["tick"] for r in got)


def test_a_full_line_drops_the_oldest_rows_and_counts_them():
    w = HistoryWriter(MemoryHistory(), queue_max=100)
    w.submit_readings([{"run_id": "r", "reading_id": f"x{i}", "tick": i, "device_id": "d"} for i in range(150)])
    assert w.queued() == 100 and w.dropped == 50
    w.flush_once()
    kept = sorted(r["tick"] for r in w.store.query_readings("r"))
    assert kept[0] == 50 and kept[-1] == 149                                         # the NEWEST 100 survive


def test_stop_writes_what_is_left_then_closes():
    sim, store = make_sim(), MemoryHistory()
    w = HistoryWriter(store, flush_seconds=60)                                       # would not flush by itself for a minute
    w.start()
    w.submit_readings(reading_rows(sim, 1))
    w.stop()
    assert len(store.query_readings(sim.run_id)) > 60


def test_health_status_has_counts_only_no_error_text():
    w = HistoryWriter(FlakyStore(fail_times=1))
    w.submit_readings([{"run_id": "r", "reading_id": "a", "tick": 1, "device_id": "d"}])
    w.flush_once()
    s = w.status()
    assert set(s) == {"backend", "healthy", "queued_rows", "written_rows", "dropped_rows", "failed_writes"}
    assert "down" not in json.dumps(s)


# ------------------------------------------------------------------ wiring: ticks and run-log lines reach the writer
def test_follow_history_stores_every_tick_the_clock_passes():
    async def go():
        sim, store = make_sim(), MemoryHistory()
        w = HistoryWriter(store)
        task = asyncio.create_task(follow_history(sim, w))
        await asyncio.sleep(0.05)
        await sim.advance(3)                                                          # ticks 1, 2, 3 (tick 0 was there at the start)
        await asyncio.sleep(0.2)
        task.cancel()
        w.flush_once()
        return sim, store
    sim, store = asyncio.run(go())
    assert sorted({r["tick"] for r in store.query_readings(sim.run_id)}) == [0, 1, 2, 3]


def test_run_log_lines_reach_the_history_and_never_hold_a_true_value(tmp_path):
    sim, book, cont, sc, rl, cfg = build(tmp_path)
    store = MemoryHistory()
    w = HistoryWriter(store)
    rl.sink = w.submit_event
    run(sc, "fake_reading")                                                           # a sensor starts to lie, the true value is private
    for t in range(sim.tick, sim.tick + 5):
        rl.log_tick(t)
    w.flush_once()
    events = store.query_events(sim.run_id)
    assert events and any(e["event_type"] == "reading" for e in events)
    assert "true_value" not in json.dumps(events, default=str)


def test_a_failing_sink_does_not_break_the_run_log(tmp_path):
    sim, book, cont, sc, rl, cfg = build(tmp_path)
    rl.sink = lambda line: 1 / 0
    cont.contain("isolate_sensor", ["AIR-01.pm25"], "stuck")                          # must not raise
    assert rl.part_path(sim.run_id).exists()


# ------------------------------------------------------------------ real PostgreSQL / TimescaleDB
@pytest.fixture()
def pg():
    from twin.storage.timescale import TimescaleHistory
    import psycopg
    with psycopg.connect(PG_DSN, autocommit=True) as c:                               # clean slate for every test
        c.execute("DROP TABLE IF EXISTS readings, events")
    store = TimescaleHistory(PG_DSN)
    yield store
    store.close()


@needs_pg
def test_pg_roundtrip_readings(pg):
    sim = make_sim()
    rows = reading_rows(sim, 7)
    pg.write_readings(rows)
    got = pg.query_readings(sim.run_id, device_id="WAT-01.water_level")
    assert len(got) == 1 and got[0]["tick"] == 7 and got[0]["unit"] == "cm"
    want = next(r for r in rows if r["device_id"] == "WAT-01.water_level")
    assert got[0]["value"] == want["value"] and (got[0]["lat"], got[0]["lon"]) == (want["lat"], want["lon"])
    assert got[0]["ts"].isoformat().startswith("2026-10-05T08:00:07")                 # SIMULATED time, not write time


@needs_pg
def test_pg_a_null_value_stays_null_and_channels_stay_apart(pg):
    sim = make_sim()
    rows = reading_rows(sim, 3)
    rows[0] = {**rows[0], "value": None}
    pg.write_readings(rows)
    got = pg.query_readings(sim.run_id, from_tick=3, to_tick=3)
    assert len(got) == len(rows) and [r["value"] for r in got if r["reading_id"] == rows[0]["reading_id"]] == [None]
    calls = [r for r in got if r["sensor"] == "emergency_calls"]
    assert {r["channel"] for r in calls} == {"accident", "fire", "flood", "medical"}


@needs_pg
def test_pg_writing_the_same_batch_twice_makes_no_duplicates(pg):
    sim = make_sim()
    rows = reading_rows(sim, 4)
    pg.write_readings(rows)
    pg.write_readings(rows)
    assert len(pg.query_readings(sim.run_id)) == len(rows)


@needs_pg
def test_pg_events_keep_their_json(pg):
    e = event_line(1, action="set_valve_position", targets=["WAT-01"], params={"position": 30})
    e["caused_by"] = ["twin-000000"]
    pg.write_events([e])
    got = pg.query_events("run-42-001", event_type="action")
    assert got[0]["data"]["params"] == {"position": 30} and got[0]["caused_by"] == ["twin-000000"]


@needs_pg
def test_pg_has_no_column_for_true_values(pg):
    import psycopg
    pg.write_readings([])                                                              # empty write does not connect
    pg._connection()                                                                   # creates the tables
    with psycopg.connect(PG_DSN) as c:
        cols = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns "
                                        "WHERE table_name IN ('readings', 'events')").fetchall()}
    assert not [c for c in cols if "true" in c or "real" in c]


@needs_pg
def test_pg_reconnects_after_the_connection_was_killed(pg):
    import psycopg
    sim = make_sim()
    pg.write_readings(reading_rows(sim, 1))
    pid = pg._conn.info.backend_pid
    with psycopg.connect(PG_DSN, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))                      # the server drops our connection
    with pytest.raises(Exception):
        pg.write_readings(reading_rows(sim, 2))                                       # this write fails ...
    pg.write_readings(reading_rows(sim, 2))                                           # ... the next one reconnects
    assert {r["tick"] for r in pg.query_readings(sim.run_id)} == {1, 2}


@needs_pg
def test_pg_writer_survives_a_database_that_is_down_then_up(pg):
    from twin.storage.timescale import TimescaleHistory
    sim = make_sim()
    store = TimescaleHistory("postgresql://twin:twinpw@127.0.0.1:1/nothing", connect_timeout=1)   # nothing listens on port 1
    w = HistoryWriter(store)
    w.submit_readings(reading_rows(sim, 1))
    w.submit_readings(reading_rows(sim, 2))
    n = w.queued()
    assert w.flush_once() is False and w.queued() == n and not w.healthy
    store._dsn = PG_DSN                                                                # the database "comes up"
    assert w.flush_once() is True and w.healthy
    assert {r["tick"] for r in store.query_readings(sim.run_id)} == {1, 2}
    store.close()


@needs_pg
def test_pg_twin_end_to_end_with_timescale_backend(monkeypatch):
    """A real Twin app with history: timescale. Its ticks end up in the database."""
    import psycopg
    from conftest import KEYS, run_twin
    from twin.settings import Secrets, Settings
    with psycopg.connect(PG_DSN, autocommit=True) as c:
        c.execute("DROP TABLE IF EXISTS readings, events")
    monkeypatch.setenv("TWIN_TIMESCALE_DSN", PG_DSN)
    cfg = load_config()
    cfg.storage.history, cfg.storage.flush_seconds = "timescale", 0.1
    cfg.clock.autorun, cfg.logging.enabled = False, False
    with run_twin(Settings(config=cfg, secrets=Secrets(**KEYS))) as (url, app):
        asyncio.run(app.state.sim.advance(2))
        import time
        deadline = time.time() + 5
        while time.time() < deadline and app.state.history.written < 100:
            time.sleep(0.1)
        assert app.state.history.status()["backend"] == "timescale" and app.state.history.healthy
    with psycopg.connect(PG_DSN) as c:
        ticks = {r[0] for r in c.execute("SELECT DISTINCT tick FROM readings").fetchall()}
    assert {0, 1, 2} <= ticks
