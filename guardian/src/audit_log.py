"""Append-only structured JSONL decision log with secret redaction."""
from __future__ import annotations

import json
import math
import os
import re
import threading
from datetime import datetime, timezone
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


def _utc_iso(value: str | int | float | None = None) -> str:
    """Normalize Twin timestamps to the shared log's RFC 3339 UTC form."""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        except ValueError:
            pass
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            numeric = float(value)
            if math.isfinite(numeric) and numeric > 0:
                return datetime.fromtimestamp(numeric, timezone.utc).isoformat(
                    timespec="milliseconds").replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            pass
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _valid_tick(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


class JsonlAuditLog:
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory or os.environ.get("GUARDIAN_AUDIT_DIR", "run-logs"))
        self._sequence_by_run: dict[str, int] = {}
        self._last_tick_by_run: dict[str, int] = {}
        self._last_timestamp_by_run: dict[str, str] = {}
        self._make_existing_logs_readable()

    def _make_existing_logs_readable(self) -> None:
        """Correct permissions on prior Guardian parts when the service starts."""
        if not self.directory.is_dir():
            return
        for path in self.directory.glob("*.guardian.jsonl"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                os.chmod(path, 0o644)
            except OSError:
                # A permission failure must not stop Guardian from starting.
                continue

    def record(self, *, run_id: str, event_type: str, reading_id: str | None,
               trust_score: float | None, verdict: str | None, action: str | None,
               decision: str, reason: str | None, caused_by: str | list[str] | None,
               data: dict[str, Any] | None = None, tick: int | None = None,
               timestamp: str | int | float | None = None) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must contain only letters, digits, dot, underscore, or hyphen")
        if caused_by is None and reading_id is not None:
            caused_by = reading_id
        if isinstance(caused_by, str):
            causes = [caused_by] if caused_by else []
        elif isinstance(caused_by, list):
            causes = [item for item in caused_by if isinstance(item, str) and item]
        else:
            causes = []
        details = data or {}
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{run_id}.guardian.jsonl"
        with _LOCK:
            if run_id not in self._sequence_by_run:
                try:
                    with path.open("r", encoding="utf-8") as existing:
                        sequence = 0
                        for line in existing:
                            sequence += 1
                            try:
                                prior = json.loads(line)
                            except (json.JSONDecodeError, TypeError):
                                continue
                            if not isinstance(prior, dict) or prior.get("run_id") != run_id:
                                continue
                            prior_tick = _valid_tick(prior.get("tick"))
                            prior_data = prior.get("data") if isinstance(prior.get("data"), dict) else {}
                            if prior_tick is None:
                                for key in ("sequence_number", "reading_tick"):
                                    prior_tick = _valid_tick(prior_data.get(key))
                                    if prior_tick is not None:
                                        break
                            if prior_tick is not None:
                                self._last_tick_by_run[run_id] = prior_tick
                            prior_timestamp = prior.get("timestamp")
                            if isinstance(prior_timestamp, (str, int, float)):
                                self._last_timestamp_by_run[run_id] = _utc_iso(prior_timestamp)
                        self._sequence_by_run[run_id] = sequence
                except FileNotFoundError:
                    self._sequence_by_run[run_id] = 0
            self._sequence_by_run[run_id] += 1
            event_id = f"guardian-{self._sequence_by_run[run_id]:06d}"

            inferred_tick = _valid_tick(tick)
            if inferred_tick is None:
                for key in ("tick", "sequence_number", "reading_tick"):
                    inferred_tick = _valid_tick(details.get(key))
                    if inferred_tick is not None:
                        break
            previous_tick = self._last_tick_by_run.get(run_id, 0)
            event_tick = _valid_tick(inferred_tick)
            if event_tick is None:
                event_tick = previous_tick
            time_value = timestamp if timestamp is not None else details.get("timestamp")
            if time_value is None:
                time_value = self._last_timestamp_by_run.get(run_id)
            event_time = _utc_iso(time_value)
            if event_tick >= previous_tick:
                self._last_tick_by_run[run_id] = event_tick
                self._last_timestamp_by_run[run_id] = event_time

            event = _redact({
                "run_id": run_id,
                "event_id": event_id,
                "timestamp": event_time,
                "tick": event_tick,
                "wall": _utc_iso(),
                "layer": "guardian",
                "event_type": event_type,
                "reading_id": reading_id,
                "trust_score": trust_score,
                "verdict": verdict,
                "requested_action": action,
                "decision": decision,
                "reason": reason,
                "caused_by": causes,
                "data": details,
            })
            line = (json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
            try:
                try:
                    os.fchmod(fd, 0o644)
                except (AttributeError, NotImplementedError, OSError):
                    os.chmod(path, 0o644)
                offset = 0
                while offset < len(line):
                    offset += os.write(fd, line[offset:])
            finally:
                os.close(fd)
        return path
