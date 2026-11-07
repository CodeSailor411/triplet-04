import hashlib
import json
import logging
import re
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

SENSITIVE_FIELDS = {
    "token",
    "api_key",
    "authorization",
    "signature",
    "private_key",
    "secret",
    "gemini_api_key",
    "openrouter_api_key",
    "access_token",
    "refresh_token",
    "approval_token",
    "signed_token",
    "true_value",
    "truth",
}
SENSITIVE_NORMALIZED = {re.sub(r"[^a-z0-9]", "", name) for name in SENSITIVE_FIELDS}

EVENT_CONTEXT: ContextVar[dict] = ContextVar("civis_brain_event_context", default={})

EVENT_NAMES = {
    "decision": "decision_made",
    "actuate_requested": "action_requested",
    "guardian_approval": "authorization_received",
    "containment_notice": "containment_notice_received",
    "feed_gap": "feed_gap_detected",
    "graph_context": "graph_context_built",
    "traffic_gnn_shadow": "graph_forecast_created",
    "traffic_gnn_interpretation": "graph_forecast_interpreted",
    "log_failure": "log_write_failed",
}

REF_FIELDS = {
    "reading_id": "reading_id",
    "reading_ids": "reading_ids",
    "source_reading_ids": "reading_ids",
    "input_reading_ids": "reading_ids",
    "evidence_reading_ids": "reading_ids",
    "device_id": "device_id",
    "device_ids": "device_ids",
    "node_id": "node_id",
    "node_ids": "node_ids",
    "action_id": "action_id",
    "jti": "jti",
    "idempotency_key": "idempotency_key",
}

OMIT_FROM_DATA = {
    "event", "run_id", "tick", "timestamp", "time", "scenario", "scenario_id",
    "summary", "refs", "reading_id", "reading_ids", "source_reading_ids",
    "device_id", "device_ids", "node_id", "node_ids", "action_id", "jti",
    "input_reading_ids", "evidence_reading_ids",
    "token_id", "idempotency_key", "batch", "readings", "token", "signature",
    "authorization", "raw_request", "raw_response",
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
        self._sequence_by_file: dict[Path, int] = {}
        self._file_lock = threading.RLock()
        self._logger = logging.getLogger("civis_brain.event_log")

    @property
    def logging_status(self) -> dict:
        return {
            "enabled": self.run_log_dir is not None,
            "error": self.write_error,
        }

    def remember_secret(self, value: str) -> None:
        if value:
            self.secrets.add(value)

    def redact(self, value):
        if isinstance(value, dict):
            return {
                key: "<redacted>" if self._sensitive_field(key) else self.redact(item)
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
            value = re.sub(r"\bg1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<redacted>", value)
            return value[:100000]
        return value

    @staticmethod
    def _sensitive_field(key) -> bool:
        normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
        if normalized == "jti":
            return False
        return (
            normalized in SENSITIVE_NORMALIZED
            or "token" in normalized
            or "secret" in normalized
            or "signature" in normalized
            or "privatekey" in normalized
            or "signingkey" in normalized
            or normalized.endswith("apikey")
            or normalized.startswith("authorization")
        )

    def append(self, event: dict) -> None:
        safe = self.redact(event)
        self.events.append(safe)
        self.events = self.events[-1000:]
        errors = []
        if self.run_log_dir is not None:
            try:
                self._write_part(safe)
            except (OSError, TypeError, ValueError) as error:
                errors.append(("event_log", error))
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(safe, allow_nan=False, ensure_ascii=False) + "\n")
            except (OSError, TypeError, ValueError) as error:
                errors.append(("trace", error))
        if errors:
            destination, error = errors[-1]
            first_failure = self.write_error is None
            if first_failure:
                self.write_error = {
                    "code": "LOG_WRITE_FAILED",
                    "destination": destination,
                    "message": type(error).__name__,
                }
                self.events.append({"event": "log_failure", **self.write_error})

    def set_clock(self, batch) -> None:
        self.clock = {"run_id": batch.run_id, "tick": batch.tick, "timestamp": batch.time}

    def _write_part(self, event: dict) -> None:
        run_id = event.get("run_id")
        if (not isinstance(run_id, str) or not run_id) and self.clock:
            run_id = self.clock.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            run_id = None

        scenario = event.get("scenario_id", event.get("scenario"))
        if not isinstance(scenario, str) or not scenario:
            scenario = None
        filename_scenario = self._filename_component(scenario.lower() if scenario else "shared")
        filename_run = self._filename_component(run_id if run_id else "unscoped")
        path = self.run_log_dir / f"{filename_scenario}-{filename_run}.city_brain.jsonl"

        timestamp = event.get("timestamp", event.get("time"))
        tick = event.get("tick")
        if timestamp is None and self.clock:
            timestamp = self.clock.get("timestamp")
        if type(tick) is not int and self.clock:
            tick = self.clock.get("tick")
        if type(tick) is not int:
            tick = None
        ts, time_basis = self._timestamp(timestamp)

        refs = self._references(event)
        data = self._event_data(event)
        if time_basis:
            data.setdefault("time_basis", time_basis)
        row = {
            "ts": ts,
            "tick": tick,
            "run_id": run_id,
            "scenario": scenario,
            "layer": "city_brain",
            "seq": 0,
            "event": EVENT_NAMES.get(event.get("event"), event.get("event", "brain_event")),
            "summary": self._summary(event),
            "refs": refs,
            "data": data,
        }
        with self._file_lock:
            row["seq"] = self._next_sequence(path)
            encoded = json.dumps(row, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab+") as stream:
                stream.seek(0, 2)
                end = stream.tell()
                if end:
                    stream.seek(-1, 2)
                    if stream.read(1) != b"\n":
                        stream.seek(0, 2)
                        stream.write(b"\n")
                stream.write(encoded.encode("utf-8") + b"\n")
                stream.flush()
            self._sequence_by_file[path] = row["seq"]

    @staticmethod
    def _filename_component(value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) and value.upper() not in {
            "CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)],
            *[f"LPT{i}" for i in range(10)],
        }:
            return value
        return "id-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    def _next_sequence(self, path: Path) -> int:
        previous = self._sequence_by_file.get(path)
        if previous is None:
            previous = 0
            if path.is_file():
                with path.open("rb") as stream:
                    for line in stream:
                        try:
                            candidate = json.loads(line)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue
                        if isinstance(candidate, dict) and type(candidate.get("seq")) is int:
                            previous = candidate["seq"]
            self._sequence_by_file[path] = previous
        return previous + 1

    @staticmethod
    def _timestamp(value) -> tuple[str, str | None]:
        if value is None:
            instant = datetime.now(timezone.utc)
            basis = "wall_utc"
        else:
            basis = None
            if isinstance(value, datetime):
                instant = value
            elif isinstance(value, str):
                try:
                    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    instant, basis = datetime.now(timezone.utc), "wall_utc_fallback"
            else:
                instant, basis = datetime.now(timezone.utc), "wall_utc_fallback"
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)
        instant = instant.astimezone(timezone.utc)
        return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z"), basis

    @staticmethod
    def _references(event: dict) -> dict:
        refs = {}
        explicit = event.get("refs")
        if isinstance(explicit, dict):
            allowed = {"reading_id", "reading_ids", "device_id", "device_ids", "node_id",
                       "node_ids", "action_id", "jti", "idempotency_key"}
            refs.update({key: value for key, value in explicit.items()
                         if key in allowed and Journal._safe_reference(value)})
        for source, target in REF_FIELDS.items():
            value = event.get(source)
            if Journal._safe_reference(value):
                refs.setdefault(target, value)
        return refs

    @staticmethod
    def _safe_reference(value) -> bool:
        return isinstance(value, str) or (
            isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value)
        )

    def _event_data(self, event: dict) -> dict:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        details = {key: value for key, value in event.items()
                   if key not in OMIT_FROM_DATA and not self._sensitive_field(key)}
        details.update({key: value for key, value in data.items()
                        if not self._sensitive_field(key)})
        return self.redact(details)

    def _summary(self, event: dict) -> str:
        if isinstance(event.get("summary"), str) and event["summary"].strip():
            summary = event["summary"].strip()
        else:
            name = event.get("event", "Brain event")
            if name == "decision":
                status = event.get("status", "recorded")
                reason = event.get("reason")
                summary = f"Brain recorded a {status} decision"
                if isinstance(reason, str) and reason:
                    summary += f": {reason}"
            elif name in {"peer_request_sent", "mcp_tool_request_sent"}:
                summary = f"Brain sent a {event.get('peer', 'peer')} request for {event.get('tool', 'a tool')}"
            elif name in {"peer_response_received", "mcp_tool_response_received"}:
                summary = f"Brain received a {event.get('peer', 'peer')} response for {event.get('tool', 'a tool')}"
                code = event.get("code")
                if code:
                    summary += f" ({code})"
            elif name == "actuate_requested":
                summary = f"Brain requested Twin action {event.get('action', 'unknown')}"
            elif name == "containment_notice":
                summary = f"Brain invalidated evidence after a {event.get('state', 'unknown')} containment notice"
            elif name == "brain_request_received":
                summary = f"Brain received {event.get('tool', 'an API')} request"
            elif name == "brain_response_sent":
                summary = f"Brain returned a response to {event.get('tool', 'an API')}"
            elif name == "incident_detected":
                nodes = event.get("node_ids", [])
                summary = f"Brain detected a {event.get('incident_kind', 'new')} incident"
                if nodes:
                    summary += " on " + ", ".join(nodes[:10])
            elif name == "incident_cleared":
                summary = "Brain cleared an incident after usable readings showed it had ended"
            elif name == "scenario_state_changed":
                summary = f"Brain updated detector state for {event.get('scenario_id', 'a scenario')}"
            elif name == "guardian_approval":
                summary = "Brain received and validated Guardian authorization for the exact action"
            elif name == "action_outcome_received":
                summary = f"Brain received Twin's {event.get('status', 'unknown')} action outcome"
            elif name == "twin_feed_state_changed":
                summary = f"Brain Twin feed is {event.get('state', 'unknown')}"
            elif name == "feed_gap":
                summary = "Brain detected a Twin feed gap or missing tick"
            elif name == "ai_request_sent":
                summary = f"Brain sent an AI request for {event.get('operation', 'planning')}"
            elif name == "ai_response_received":
                summary = f"Brain received an AI {event.get('outcome', 'unknown')} response"
            elif name == "traffic_gnn_shadow":
                summary = f"Brain graph forecast status: {event.get('status', 'unknown')}"
            else:
                summary = f"Brain recorded {str(name).replace('_', ' ')}"
        return self.redact(summary)[:500]
