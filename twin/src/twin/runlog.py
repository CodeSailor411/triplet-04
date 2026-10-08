"""The run log (R2): every scenario run leaves a log file in the repo.

Two steps, so three layers never write into one file at the same time:
  1. Each layer writes its OWN part file while it runs. The Twin's is  <parts_dir>/<run_id>.twin.jsonl
  2. A merge step puts all the parts together, in time order, into ONE file per run: <merged_dir>/<run_id>.jsonl
     (the spec's `logs/` folder, "one file per run").

The file format is JSON Lines: one JSON object per line. Why: if the Twin crashes, only the last line can be broken,
and a program can read the file while it is still being written. The format below is OUR DRAFT (proposed to CIVIS and
9antra, review on 9 Oct). All of it is in this one file, so a change is cheap.

Every line has:
  run_id, event_id (twin-000001), timestamp (simulated time of the tick), tick, wall (real clock, orders events inside one
  tick), layer, event_type, caused_by (list of earlier event_ids), data (depends on event_type).
Event types the Twin writes: scenario, reading, action, containment.
  reading     only readings a scenario fault touched (109 per tick would be huge). A verdict that points at a normal reading
              finds no matching reading here. That gap is on purpose.
  action      what `actuate` answered. Only the token's ID is logged, never the token (a logged token could be replayed).

The shared log must never hold a true value. True values go to <parts_dir>/<run_id>.twin-private.jsonl, which is never merged.
The log is for people (and the dashboard) to read AFTERWARDS. Layers must not read it to make decisions.
"""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import LoggingCfg

log = logging.getLogger("twin.runlog")

LAYER_ORDER = {"twin": 0, "guardian": 1, "brain": 2}


def _wall() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RunLog:
    def __init__(self, cfg: LoggingCfg, sim, scenarios, run_info: dict[str, Any]):
        self.cfg, self.sim, self.scenarios, self.run_info = cfg, sim, scenarios, run_info
        self.enabled = cfg.enabled
        self.parts_dir, self.merged_dir = Path(cfg.parts_dir), Path(cfg.merged_dir)
        self._lock = threading.Lock()
        self._run: int | None = None            # run_number the open files belong to
        self._run_id = ""
        self._n = 0                              # last event number in the part file
        self._warned = False

    # ------------------------------------------------------------------ files
    def part_path(self, run_id: str) -> Path:
        return self.parts_dir / f"{run_id}.twin.jsonl"

    def private_path(self, run_id: str) -> Path:
        return self.parts_dir / f"{run_id}.twin-private.jsonl"

    def merged_path(self, run_id: str) -> Path:
        return self.merged_dir / f"{run_id}.jsonl"

    def _append(self, path: Path, line: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:          # one short line, flushed at once: a crash loses at most the last line
            f.write(json.dumps(line, separators=(",", ":"), ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ writing events
    def record(self, event_type: str, data: dict[str, Any], *, caused_by: list[str] | None = None) -> str | None:
        """Write one event of the Twin. Returns its event_id. Never raises: a full disk must not stop the Twin."""
        if not self.enabled:
            return None
        try:
            with self._lock:
                self._open_run_if_new()
                return self._write(event_type, data, caused_by)
        except OSError as e:
            self._warn(e)
            return None

    def _write(self, event_type: str, data: dict[str, Any], caused_by: list[str] | None, tick: int | None = None) -> str:
        tick = self.sim.tick if tick is None else tick        # a reading event carries the tick it describes
        self._n += 1
        eid = f"twin-{self._n:06d}"
        self._append(self.part_path(self._run_id), {
            "run_id": self._run_id, "event_id": eid, "timestamp": self.sim.clock.iso_of(tick), "tick": tick, "wall": _wall(),
            "layer": "twin", "event_type": event_type, "caused_by": caused_by or [], "data": data})
        return eid

    def _open_run_if_new(self) -> None:
        """First event of a run: remember the run, continue numbering if the part file already exists (a restart reuses the run id)."""
        if self._run == self.sim.run_number:
            return
        self._run, self._run_id = self.sim.run_number, self.sim.run_id
        path = self.part_path(self._run_id)
        self._n = sum(1 for _ in open(path, encoding="utf-8")) if path.exists() else 0
        self._write("scenario", {"phase": "run_started", **self.run_info}, None)

    def _warn(self, e: Exception) -> None:
        if not self._warned:                                   # say it once, not on every tick
            self._warned = True
            log.warning("Run log could not be written (%s). The Twin keeps running without it.", e)

    # ------------------------------------------------------------------ faulted readings
    def log_tick(self, tick: int) -> None:
        """Write the readings a scenario fault touched at this tick, and (privately) the true values behind them."""
        if not self.enabled or self.scenarios is None:
            return
        rows = []
        for f in self.scenarios.active_faults(tick):
            d = self.scenarios.devices[f.device_id]
            if self.sim.overlay is not None and self.sim.overlay.is_hidden(d.device_id, tick):
                continue                                       # cut off from the feed: nobody saw it
            for ch in ([f.channel] if f.channel else list(d.channels or (None,))):
                r = self.sim.reported(d, ch, tick)
                rows.append((f, d, ch, r))
        if not rows:
            return
        try:
            with self._lock:
                self._open_run_if_new()
                for f, d, ch, r in rows:
                    eid = self._write("reading", {"reading_id": r.reading_id, "reading_tick": r.tick, "node_id": r.node_id,
                                                  "device_id": r.device_id, "sensor": r.sensor, "channel": r.channel,
                                                  "value": r.value, "unit": r.unit},
                                      [self.scenarios.event_id_of(f.scenario_id)] if self.scenarios.event_id_of(f.scenario_id) else [],
                                      tick=tick)
                    self._append(self.private_path(self._run_id), {
                        "run_id": self._run_id, "tick": tick, "wall": _wall(), "event_id": eid, "reading_id": r.reading_id,
                        "device_id": d.device_id, "channel": ch, "reported_value": r.value,
                        "true_value": self.sim.model.true_value(d, ch, tick), "fault_id": f.fault_id, "fault_kind": f.kind})
        except OSError as e:
            self._warn(e)

    async def follow_clock(self) -> None:
        """Background job: for every tick that passes, log the faulted readings."""
        seen_run, seen_tick = self.sim.run_number, -1
        while True:
            run, tick = self.sim.run_number, self.sim.tick
            if run != seen_run:                                 # a new run starts again at tick 0
                seen_run, seen_tick = run, -1
            for t in range(seen_tick + 1, tick + 1):
                self.log_tick(t)
            seen_tick = tick
            await self.sim.wait_for_change(run, tick, 1.0)

    # ------------------------------------------------------------------ merging
    def export(self, extra_parts: list[Path] | None = None) -> Path | None:
        """(Re)write the merged file of the current run from every part we can find."""
        if not self.enabled or self._run is None:
            return None
        try:
            return merge_parts([self.part_path(self._run_id), *(extra_parts or [])], self.merged_path(self._run_id))
        except OSError as e:
            self._warn(e)
            return None

    def end_run(self) -> Path | None:
        """The run is over (reset or shutdown): write a closing event, then the merged file."""
        if not self.enabled or self._run is None:
            return None
        self.record("scenario", {"phase": "run_ended"})
        return self.export()


# ---------------------------------------------------------------------- merge (also used by the command line tool)
def read_part(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Read a part file. A line that is not valid JSON (for example a half-written last line) is skipped and counted."""
    events, bad = [], 0
    if not Path(path).exists():
        return events, bad
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and {"run_id", "event_id", "tick", "layer", "event_type"} <= obj.keys():
                    events.append(obj)
                    continue
            except json.JSONDecodeError:
                pass
            bad += 1
    return events, bad


def merge_parts(parts: list[Path], out: Path) -> Path:
    """Put the events of all part files in one list, in time order, and write it to `out` in one go (no half-written file).

    Order: tick, then real clock (wall), then layer, then event number. Events of different runs are refused:
    a merged file belongs to exactly one run.
    """
    events: list[dict[str, Any]] = []
    for p in parts:
        got, bad = read_part(p)
        if bad:
            log.warning("%s: %d unreadable line(s) skipped", p, bad)
        events += got
    if len({e["run_id"] for e in events}) > 1:
        raise ValueError(f"Parts belong to different runs: {sorted({e['run_id'] for e in events})}")
    events.sort(key=lambda e: (e["tick"], e.get("wall", ""), LAYER_ORDER.get(e["layer"], 9), e["event_id"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, separators=(",", ":"), ensure_ascii=False) + "\n")
    os.replace(tmp, out)                                         # the old file is swapped for the new one in one step
    return out
