"""Authenticated Brain verdict webhook with a small durable JSONL outbox."""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import time
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class BrainDeliveryError(RuntimeError):
    pass


def brain_config() -> dict[str, Any] | None:
    """Return validated Brain webhook settings, or None when delivery is disabled."""
    endpoint = os.environ.get("BRAIN_VERDICT_URL", "").strip()
    key = os.environ.get("GUARDIAN_BRAIN_BEARER_KEY", "").strip()
    if not endpoint and not key:
        return None
    if not endpoint or not key:
        raise BrainDeliveryError("BRAIN_VERDICT_URL and GUARDIAN_BRAIN_BEARER_KEY must be configured together")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise BrainDeliveryError("BRAIN_VERDICT_URL must be an absolute HTTP(S) URL without embedded credentials")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise BrainDeliveryError("Brain bearer credentials require HTTPS except for a loopback test server")
    try:
        timeout = float(os.environ.get("BRAIN_TIMEOUT_SECONDS", "10"))
        retries = int(os.environ.get("BRAIN_MAX_RETRIES", "3"))
        retry_base = float(os.environ.get("BRAIN_RETRY_BASE_SECONDS", "0.5"))
    except ValueError as exc:
        raise BrainDeliveryError("Brain timeout/retry settings must be numeric") from exc
    if not 0 < timeout <= 120 or not 0 <= retries <= 10 or not 0 <= retry_base <= 10:
        raise BrainDeliveryError("Brain timeout must be (0,120], retries [0,10], and retry base [0,10]")
    return {
        "url": endpoint,
        "bearer_key": key,
        "timeout": timeout,
        "max_retries": retries,
        "retry_base_seconds": retry_base,
        "outbox": Path(os.environ.get("GUARDIAN_BRAIN_OUTBOX", "run-logs/brain-outbox.jsonl")),
    }


def verdict_payload(run_id: str, evaluation: dict[str, Any]) -> dict[str, Any] | None:
    """Map a Guardian evaluation to the versioned Brain webhook contract.

    Security-gate rejections have no scored Guardian verdict and are not
    mislabeled as one; their Twin caller still receives the original result.
    """
    guardian = evaluation.get("guardian")
    if not isinstance(guardian, dict):
        return None
    reading_id = evaluation.get("reading_id")
    sensor_id = evaluation.get("sensor_id")
    if not isinstance(reading_id, str) or not reading_id or not isinstance(sensor_id, str) or not sensor_id:
        raise BrainDeliveryError("Guardian evaluation is missing its reading or sensor ID")
    city_brain = evaluation.get("city_brain") or {}
    ml = evaluation.get("ml") or {}
    identity = hashlib.sha256(f"{run_id}:{reading_id}".encode("utf-8")).hexdigest()
    return {
        "schema_version": "guardian.verdict.v1",
        "event_id": identity,
        "run_id": run_id,
        "reading_id": reading_id,
        "sensor_id": sensor_id,
        "timestamp": evaluation.get("timestamp"),
        "verdict": guardian.get("verdict"),
        "trust_score": guardian.get("trust_score"),
        "reasons": guardian.get("reasons", []),
        "city_brain": {
            "status": city_brain.get("status"),
            "allowed": city_brain.get("allowed"),
            "action": city_brain.get("action"),
            "reason": city_brain.get("reason"),
            "simulated_only": city_brain.get("simulated_only", True),
        },
        "model_advisory": {
            "label": ml.get("label"),
            "probability": ml.get("probability"),
            "model_version": ml.get("model_version"),
            "advisory_only": True,
        },
    }


class VerdictOutbox:
    """Append-only retry queue; idempotency keys make restart replay safe."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = Lock()
        self._states: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        event_id = record["event_id"]
                        state = record["state"]
                        if state == "pending":
                            self._states[event_id] = record["payload"]
                        elif state == "delivered":
                            self._states.pop(event_id, None)
                    except (json.JSONDecodeError, KeyError, TypeError) as exc:
                        raise BrainDeliveryError(f"Invalid Brain outbox record on line {line_number}") from exc

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        with self.path.open("ab") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())

    def enqueue(self, payload: dict[str, Any]) -> None:
        event_id = payload["event_id"]
        with self._lock:
            if event_id in self._states:
                return
            self._append({"state": "pending", "event_id": event_id, "payload": payload})
            self._states[event_id] = payload

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._states.values())

    def mark_delivered(self, event_id: str) -> None:
        with self._lock:
            if event_id in self._states:
                self._append({"state": "delivered", "event_id": event_id})
                del self._states[event_id]


def post_verdict(payload: dict[str, Any], *, url: str, bearer_key: str,
                 timeout: float = 10, max_retries: int = 3,
                 retry_base_seconds: float = 0.5) -> int:
    """POST one verdict; retry network errors, 408/429 and 5xx only."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bearer_key}",
        "Idempotency-Key": payload["event_id"],
    })
    for attempt in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
                if 200 <= response.status < 300:
                    return response.status
                status = response.status
                retryable = status in {408, 429} or status >= 500
                message = f"Brain returned HTTP {status}"
        except HTTPError as exc:
            status = exc.code
            retryable = status in {408, 429} or status >= 500
            message = f"Brain returned HTTP {status}"
        except (URLError, TimeoutError, OSError) as exc:
            status = None
            retryable = True
            message = f"Brain request failed: {type(exc).__name__}: {exc}"
        if not retryable or attempt >= max_retries:
            raise BrainDeliveryError(message)
        time.sleep(min(retry_base_seconds * (2 ** attempt), 8.0))
    raise BrainDeliveryError("Brain delivery failed")
