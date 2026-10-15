"""A background writer between the Twin and the history store.

Why a separate thread: a database call can be slow or can hang. The Twin's clock, the live feed and the MCP tools
must never wait for it. So the Twin only drops rows into a waiting line (a queue) and goes on. This thread takes
rows out and writes them in batches.

Rules (all of them are tested):
  * submit_* never blocks and never raises.
  * If the database fails, the batch goes back to the front of the line and the writer tries again after a pause.
    Retrying is safe because the store skips rows it already has.
  * The line has a size limit. If the database stays down so long that the line is full, the OLDEST rows are thrown
    away and counted in `dropped`. The Twin keeps its memory under control instead of growing forever.
  * stop() makes one last try to write what is left, then closes the store.
"""
import collections
import logging
import threading
from typing import Any

from .base import HistoryStore

log = logging.getLogger("twin.storage")


class HistoryWriter:
    def __init__(self, store: HistoryStore, *, queue_max: int = 50_000, flush_seconds: float = 1.0,
                 batch_max: int = 2000, retry_seconds: float = 2.0):
        self.store = store
        self.queue_max, self.flush_seconds, self.batch_max, self.retry_seconds = queue_max, flush_seconds, batch_max, retry_seconds
        self._readings: collections.deque[dict[str, Any]] = collections.deque()
        self._events: collections.deque[dict[str, Any]] = collections.deque()
        self._lock = threading.Lock()                 # protects the two lines and the counters
        self._wake = threading.Event()                # tells the thread "there is work / stop"
        self._stop = False
        self._thread: threading.Thread | None = None
        self.written = 0                              # rows the store accepted
        self.dropped = 0                              # rows thrown away because the line was full
        self.failures = 0                             # failed write attempts
        self.healthy = True                           # False after a failed write, True after the next good one
        self._warned = False

    # ------------------------------------------------------------------ the Twin's side: never blocks, never raises
    def submit_readings(self, rows: list[dict[str, Any]]) -> None:
        self._put(self._readings, rows)

    def submit_event(self, line: dict[str, Any]) -> None:
        self._put(self._events, [line])

    def _put(self, line: collections.deque, rows: list[dict[str, Any]]) -> None:
        with self._lock:
            line.extend(rows)
            over = len(self._readings) + len(self._events) - self.queue_max
            while over > 0:                           # full: throw away the oldest rows (readings first, they are the most)
                (self._readings if self._readings else self._events).popleft()
                self.dropped += 1
                over -= 1
        self._wake.set()

    # ------------------------------------------------------------------ the thread
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="history-writer", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
        try:
            self.store.close()
        except Exception:                             # closing must not break shutdown
            pass

    def _run(self) -> None:
        while not self._stop:
            self._wake.wait(self.flush_seconds)
            self._wake.clear()
            ok = self.flush_once()
            if not ok and not self._stop:
                self._wake.wait(self.retry_seconds)   # database trouble: pause before the next try
                self._wake.clear()
        self.flush_once()                             # last try at shutdown

    def flush_once(self) -> bool:
        """Write everything that is waiting. True if nothing is left or everything went through."""
        while True:
            with self._lock:
                readings = [self._readings.popleft() for _ in range(min(self.batch_max, len(self._readings)))]
                events = [self._events.popleft() for _ in range(min(self.batch_max, len(self._events)))]
            if not readings and not events:
                return True
            try:
                self.store.write_events(events)       # events first: they are few and explain the readings
                self.store.write_readings(readings)
            except Exception as e:                    # any backend error: keep the rows and try again later
                with self._lock:
                    self._readings.extendleft(reversed(readings))     # back to the FRONT, original order
                    self._events.extendleft(reversed(events))
                self.failures += 1
                self.healthy = False
                if not self._warned:                  # say it once, not every second
                    self._warned = True
                    log.warning("History store write failed (%s: %s). The Twin keeps running; rows wait in memory.",
                                type(e).__name__, str(e).splitlines()[0][:200] if str(e) else "")
                return False
            with self._lock:
                self.written += len(readings) + len(events)
            if not self.healthy:
                log.info("History store is back.")
            self.healthy, self._warned = True, False

    def queued(self) -> int:
        with self._lock:
            return len(self._readings) + len(self._events)

    def status(self) -> dict[str, Any]:
        """Safe to show on /health: counts only, no error text (error text can contain host names)."""
        return {"backend": self.store.name, "healthy": self.healthy, "queued_rows": self.queued(),
                "written_rows": self.written, "dropped_rows": self.dropped, "failed_writes": self.failures}
