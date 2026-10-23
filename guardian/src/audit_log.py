"""Append-only structured JSONL decision log with secret redaction."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_SECRET_KEYS = {
    "token", "signed_token", "signedtoken", "full_token", "fulltoken",
    "authorization", "bearer", "bearer_key", "bearerkey",
    "private_key", "privatekey", "secret", "signature",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in _SECRET_KEYS else _redact(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_redact(v) for v in value]
    return value


class JsonlAuditLog:
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory or os.environ.get("GUARDIAN_AUDIT_DIR", "run-logs"))

    def record(self, *, run_id: str, event_type: str, reading_id: str | None,
               trust_score: float | None, verdict: str | None, action: str | None,
               decision: str, reason: str | None, caused_by: str | None,
               data: dict[str, Any] | None = None) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must contain only letters, digits, dot, underscore, or hyphen")
        if caused_by is None and reading_id is not None:
            caused_by = reading_id
        event = _redact({
            "timestamp": time.time(), "run_id": run_id, "event_type": event_type,
            "reading_id": reading_id, "trust_score": trust_score, "verdict": verdict,
            "requested_action": action, "decision": decision, "reason": reason,
            "caused_by": caused_by, "data": data or {},
        })
        line = (json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{run_id}.guardian.jsonl"
        with _LOCK:
            fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                offset = 0
                while offset < len(line):
                    offset += os.write(fd, line[offset:])
            finally:
                os.close(fd)
        return path
