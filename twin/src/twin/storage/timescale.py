"""History in TimescaleDB (PostgreSQL with the time-series extension), through psycopg 3.

TimescaleDB = normal PostgreSQL plus a "hypertable": a table that is cut into time chunks behind the scenes, so
inserting new rows and asking for a time range stay fast when the table gets huge. Everything else is plain SQL.

IMPORTANT (what is and is not verified): the SQL below runs on plain PostgreSQL too. The one TimescaleDB-only step,
`create_hypertable`, runs only when the extension exists. If it does not, the table stays a normal table and the Twin
logs that once. So the Twin works either way, but only a real TimescaleDB server proves the hypertable step.

Time column: `ts` is the SIMULATED time of the reading (what the reading says, not when the row was written).
A hypertable needs the time column inside every unique key, so the primary key is (run_id, reading_id, ts).
"""
import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

log = logging.getLogger("twin.storage")

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS readings (
        run_id     text             NOT NULL,
        reading_id text             NOT NULL,
        ts         timestamptz      NOT NULL,
        tick       integer          NOT NULL,
        node_id    text             NOT NULL,
        device_id  text             NOT NULL,
        sensor     text             NOT NULL,
        channel    text,
        value      double precision,
        unit       text             NOT NULL,
        lat        double precision NOT NULL,
        lon        double precision NOT NULL,
        PRIMARY KEY (run_id, reading_id, ts)
    )""",
    "CREATE INDEX IF NOT EXISTS readings_by_device ON readings (run_id, device_id, tick)",
    """CREATE TABLE IF NOT EXISTS events (
        run_id     text        NOT NULL,
        event_id   text        NOT NULL,
        ts         timestamptz NOT NULL,
        tick       integer     NOT NULL,
        wall       timestamptz NOT NULL,
        layer      text        NOT NULL,
        event_type text        NOT NULL,
        caused_by  jsonb       NOT NULL,
        data       jsonb       NOT NULL,
        PRIMARY KEY (run_id, event_id)
    )""",
]

INSERT_READING = """INSERT INTO readings (run_id, reading_id, ts, tick, node_id, device_id, sensor, channel, value, unit, lat, lon)
    VALUES (%(run_id)s, %(reading_id)s, %(timestamp)s::timestamptz, %(tick)s, %(node_id)s, %(device_id)s, %(sensor)s,
            %(channel)s, %(value)s, %(unit)s, %(lat)s, %(lon)s)
    ON CONFLICT DO NOTHING"""          # ON CONFLICT DO NOTHING = "if this row is already there, skip it"

INSERT_EVENT = """INSERT INTO events (run_id, event_id, ts, tick, wall, layer, event_type, caused_by, data)
    VALUES (%(run_id)s, %(event_id)s, %(timestamp)s::timestamptz, %(tick)s, %(wall)s::timestamptz, %(layer)s,
            %(event_type)s, %(caused_by)s, %(data)s)
    ON CONFLICT DO NOTHING"""


class TimescaleHistory:
    name = "timescale"

    def __init__(self, dsn: str, *, connect_timeout: int = 3):
        self._dsn, self._timeout = dsn, connect_timeout
        self._conn: psycopg.Connection | None = None
        self.hypertable = False                 # True once create_hypertable worked

    # ------------------------------------------------------------------ connection
    def _connection(self) -> psycopg.Connection:
        """Connect when needed. Called before every write, so a database that came back is picked up again."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self._dsn, connect_timeout=self._timeout, row_factory=dict_row)
            self._ensure_schema(self._conn)
        return self._conn

    def _drop_connection(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except psycopg.Error:
            pass
        self._conn = None

    def _ensure_schema(self, conn: psycopg.Connection) -> None:
        with conn.transaction():
            for stmt in SCHEMA:
                conn.execute(stmt)
        with conn.transaction():
            has_ext = conn.execute("SELECT 1 AS x FROM pg_available_extensions WHERE name = 'timescaledb'").fetchone()
            if has_ext:
                conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
                conn.execute("SELECT create_hypertable('readings', 'ts', if_not_exists => TRUE)")
                self.hypertable = True
        if not self.hypertable:
            log.warning("TimescaleDB extension not available: history uses a plain PostgreSQL table.")

    # ------------------------------------------------------------------ writing
    def write_readings(self, rows: list[dict[str, Any]]) -> None:
        self._write(INSERT_READING, rows)

    def write_events(self, rows: list[dict[str, Any]]) -> None:
        self._write(INSERT_EVENT, [{**e, "caused_by": Jsonb(e.get("caused_by", [])), "data": Jsonb(e.get("data", {}))}
                                   for e in rows])

    def _write(self, sql: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        try:
            conn = self._connection()
            with conn.transaction():             # all rows of the batch go in together, or none do
                conn.cursor().executemany(sql, rows)
        except psycopg.Error:
            self._drop_connection()              # next write opens a fresh connection
            raise

    # ------------------------------------------------------------------ reading back
    def query_readings(self, run_id, *, device_id=None, from_tick=None, to_tick=None):
        sql = ("SELECT run_id, reading_id, ts, tick, node_id, device_id, sensor, channel, value, unit, lat, lon "
               "FROM readings WHERE run_id = %s AND (%s::text IS NULL OR device_id = %s) "
               "AND (%s::int IS NULL OR tick >= %s) AND (%s::int IS NULL OR tick <= %s) ORDER BY tick, reading_id")
        args = (run_id, device_id, device_id, from_tick, from_tick, to_tick, to_tick)
        return self._connection().execute(sql, args).fetchall()

    def query_events(self, run_id, *, event_type=None):
        sql = ("SELECT run_id, event_id, ts, tick, wall, layer, event_type, caused_by, data FROM events "
               "WHERE run_id = %s AND (%s::text IS NULL OR event_type = %s) ORDER BY event_id")
        return self._connection().execute(sql, (run_id, event_type, event_type)).fetchall()

    def close(self) -> None:
        self._drop_connection()
