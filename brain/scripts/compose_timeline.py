"""Project observed Brain and Guardian audit events into Twin's timeline format."""

import hashlib
import json
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path


def brain_event(row):
    if row.get("layer") != "city_brain" or row.get("event") not in {
        "decision_made", "action_requested",
    }:
        return None
    data, refs = row.get("data", {}), row.get("refs", {})
    action = data.get("action")
    return {
        "tick": row.get("tick"), "layer": "brain", "event_type": "decision",
        "timestamp": row.get("ts") or "",
        "caused_by": refs.get("reading_ids", []),
        "data": {
            "chosen_action": action, "incident": row.get("scenario"),
            "status": data.get("status", "requested"),
            "reason": data.get("reason"), "code": data.get("peer_code"),
            "targets": data.get("targets"), "idempotency_key": refs.get("idempotency_key"),
        },
    }


class Timeline:
    def __init__(self, output):
        self.output = output
        self.offsets = {}
        self.seen = {}
        self.evidence_ticks = OrderedDict()

    def guardian_event(self, row):
        kind, reading_id = row.get("event_type"), row.get("reading_id")
        score, data = row.get("trust_score"), row.get("data", {})
        if not isinstance(reading_id, str) or kind not in {"reading_evaluated", "action_decision"}:
            return None
        reading = (row["run_id"], reading_id)
        if kind == "reading_evaluated":
            tick = data.get("sequence_number")
            if type(tick) is not int:
                return None
            self.evidence_ticks[reading] = tick
            self.evidence_ticks.move_to_end(reading)
            if len(self.evidence_ticks) > 50000:
                self.evidence_ticks.popitem(last=False)
            if type(score) not in (int, float) or not 0 <= score <= 1:
                return None
            fields = {"device_id": data.get("sensor_id"), "score": score,
                      "verdict": row.get("verdict")}
        else:
            tick = self.evidence_ticks.get(reading)
            if tick is None or row.get("decision") not in {"approved", "denied"}:
                return None
            fields = {"approved_action": row.get("requested_action"), "score": score,
                      "decision": row["decision"], "reason": row.get("reason"),
                      "token_id": data.get("token_id"), "idempotency_key": data.get("idempotency_key"),
                      "tick_basis": "evidence"}
        wall = row.get("wall") or row.get("timestamp")
        if type(wall) in (int, float):
            wall = datetime.fromtimestamp(wall, timezone.utc).isoformat()
        timestamp = wall if isinstance(wall, str) else ""
        return {"tick": tick, "layer": "guardian", "event_type": "verdict",
                "wall": timestamp, "timestamp": timestamp,
                "caused_by": [reading_id], "data": fields}

    def poll(self, source, adapt):
        with source.open("rb") as stream:
            stat = source.stat()
            inode, offset = self.offsets.get(source, (None, 0))
            if inode != stat.st_ino or stat.st_size < offset:
                offset = 0
            stream.seek(offset)
            while line := stream.readline():
                if not line.endswith(b"\n"):
                    break
                try:
                    row = json.loads(line)
                    run_id = row.get("run_id")
                    if isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
                        event = adapt(row)
                        if event is not None and type(event["tick"]) is int:
                            self.emit(run_id, line, event)
                except (AttributeError, KeyError, ValueError, TypeError, OverflowError):
                    # Incomplete lines wait for the next poll; malformed complete rows are skipped.
                    pass
                self.offsets[source] = (stat.st_ino, stream.tell())

    def emit(self, run_id, line, event):
        target = self.output / f"{run_id}.{event['layer']}.jsonl"
        if target not in self.seen:
            existing = set()
            if target.exists():
                for previous in target.read_bytes().splitlines():
                    try:
                        existing.add(json.loads(previous)["event_id"])
                    except (KeyError, TypeError, ValueError):
                        continue
            self.seen[target] = existing
        digest = hashlib.sha256(line).hexdigest()[:32]
        event_id = f"{event['layer']}-{digest}"
        if self.seen[target].isdisjoint((event_id, f"civis-{digest}")):
            with target.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({**event, "event_id": event_id, "run_id": run_id},
                                        allow_nan=False) + "\n")
            self.seen[target].add(event_id)


def main():
    output = Path("run-logs")
    output.mkdir(parents=True, exist_ok=True)
    timeline = Timeline(output)
    while True:
        for source in sorted(Path("logs").glob("*.city_brain.jsonl")):
            timeline.poll(source, brain_event)
        for source in sorted(Path("../guardian/run-logs").glob("*.guardian.jsonl")):
            timeline.poll(source, timeline.guardian_event)
        time.sleep(1)


if __name__ == "__main__":
    main()
