import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SENSITIVE_FIELDS = {
    "token",
    "api_key",
    "authorization",
    "private_key",
    "gemini_api_key",
    "openrouter_api_key",
    "true_value",
    "truth",
}


class Journal:
    def __init__(self, path: Path | None = None, secrets: list[str] | None = None,
                 run_log_dir: Path | None = None):
        self.path = path
        self.run_log_dir = run_log_dir
        self.clock = None
        self.write_error = None
        self.secrets = set(filter(None, secrets or []))
        self.events: list[dict] = []

    def remember_secret(self, value: str) -> None:
        if value:
            self.secrets.add(value)

    def redact(self, value):
        if isinstance(value, dict):
            return {
                key: "<redacted>" if key.lower() in SENSITIVE_FIELDS else self.redact(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.redact(item) for item in value]
        if isinstance(value, str):
            for secret in sorted(self.secrets, key=len, reverse=True):
                value = value.replace(secret, "<redacted>")
            value = re.sub(r"Bearer\s+\S+", "Bearer <redacted>", value, flags=re.I)
            value = re.sub(
                r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*", "<redacted>", value
            )
            value = re.sub(r"sk-or-v1-[A-Za-z0-9_-]+", "<redacted>", value)
            return value[:100000]
        return value

    def append(self, event: dict) -> None:
        safe = self.redact(event)
        self.events.append(safe)
        self.events = self.events[-1000:]
        try:
            self._write_part(safe)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(safe, allow_nan=False, ensure_ascii=False) + "\n")
        except OSError:
            self.write_error = {"code": "LOG_WRITE_FAILED",
                                "message": "Audit file could not be written; in-memory trace retained"}
            if not self.events or self.events[-1].get("event") != "log_failure":
                self.events.append({"event": "log_failure", **self.write_error})


    def set_clock(self, batch) -> None:
        self.clock = {"run_id": batch.run_id, "tick": batch.tick, "timestamp": batch.time}

    def _write_part(self, event: dict) -> None:
        if self.run_log_dir is None or self.clock is None:
            return
        run_id = event.get("run_id", self.clock["run_id"])
        if run_id != self.clock["run_id"]:
            return
        # Preserve normal run IDs; unsafe Windows filenames receive a stable local name.
        filename = run_id if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id) else (
            "run-" + hashlib.sha256(run_id.encode()).hexdigest()[:24]
        )
        if filename.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)],
                               *[f"LPT{i}" for i in range(10)]}:
            filename = "run-" + filename
        row = {
            **self.clock, "run_id": run_id,
            "event_id": "brain-" + uuid4().hex,
            "wall": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "layer": "brain",
            "event_type": event.get("event", "decision"),
            "caused_by": event.get("source_reading_ids", event.get("reading_ids", [])),
            "data": {key: value for key, value in event.items()
                     if key not in {"run_id", "tick", "event"}},
        }
        self.run_log_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_log_dir / f"{filename}.brain.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, allow_nan=False, ensure_ascii=False) + "\n")
