"""Single FastAPI entry point for the Guardian + RF + City Brain mock."""
from __future__ import annotations

import time
import hmac
import hashlib
import json
import math
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, model_validator
from cryptography.hazmat.primitives import serialization
from starlette.responses import JSONResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUARDIAN_ROOT = PROJECT_ROOT
if str(GUARDIAN_ROOT) not in sys.path:
    sys.path.insert(0, str(GUARDIAN_ROOT))

from app import METADATA, describe_capabilities, load_model, predict_reading, server as mcp_server
from integration_service import service
from mocks.simulation import SENSORS, run_scenario, scenario_catalog
from action_policy import ActionPolicy, ActionPolicyError
from audit_log import JsonlAuditLog
from brain_client import BrainDeliveryError, notify_containment_mcp_sync
from token_service import ActionTokenService, TokenError
from twin_adapter import normalize_twin_reading
from contract import (MCP_TOOL_AUTHORIZE_ACTION, MCP_TOOL_GET_TRUST_VERDICT,
                      MCP_TOOL_VERIFY_ACTION_TOKEN, TRUST_STATE_MAP)
from guardian_config import GuardianSettings, MIN_HISTORY_FOR_STATISTICAL_DRIFT
from twin_discovery import (TwinDiscoveryError, call_twin_tool_sync, discover_twin_sync,
                            read_twin_clock_sync, TwinToolRejected)


SensorType = Literal["traffic_cam", "water_level", "power_load", "air_quality", "emergency_call", "units_free"]
IncidentType = Literal["fire", "flood", "accident", "traffic_jam", "cyberattack"]
ALLOWED_UNITS = {
    "traffic_cam": {"percent", "%"},
    "water_level": {"cm", "centimeter", "centimeters", "m", "meter", "meters"},
    "power_load": {"kW"},
    "air_quality": {"AQI", "ug/m3", "µg/m³"},
    "emergency_call": {"calls_per_min", "calls/min"},
    "units_free": {"units"},
}


def _validate_twin_event_refs(values: list[str]) -> list[str]:
    if len(values) > 10 or any(not re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", value) for value in values):
        raise ValueError("caused_by must contain at most 10 Twin event IDs (1-80 letters, digits, . _ : -)")
    return values


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor_id: str = Field(min_length=1, max_length=128)
    sensor_type: SensorType
    value: FiniteFloat
    unit: str = Field(min_length=1, max_length=32)
    timestamp: FiniteFloat = Field(gt=0)
    location: dict[str, FiniteFloat]
    sequence_number: StrictInt = Field(ge=0)
    channel: str | None = Field(default=None, min_length=1, max_length=32)
    node_id: str | None = Field(default=None, min_length=1, max_length=128)
    signature: str | None = Field(default=None, max_length=256)
    incident_type: IncidentType | None = None
    reading_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_unit_and_location(self):
        if self.unit not in ALLOWED_UNITS[self.sensor_type]:
            raise ValueError(f"unit {self.unit!r} is not supported for {self.sensor_type}")
        if self.sensor_type == "units_free" and self.channel not in {"police", "ambulance", "fire"}:
            raise ValueError("units_free requires a police, ambulance, or fire channel")
        if self.sensor_type == "emergency_call" and self.channel is not None and self.channel not in {
            "accident", "fire", "flood", "medical",
        }:
            raise ValueError("emergency_call channel is not supported")
        if not {"lat", "lng"} <= set(self.location):
            raise ValueError("location must include finite lat and lng values")
        if not -90 <= self.location["lat"] <= 90 or not -180 <= self.location["lng"] <= 180:
            raise ValueError("location coordinates are out of range")
        return self


class IncidentReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=1, max_length=128)
    incident_type: IncidentType
    evidence: dict


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sensor_id: str | None = Field(default=None, min_length=1, max_length=128)
    reading_id: str | None = Field(default=None, min_length=1, max_length=128)
    reading_ids: list[str] = Field(default_factory=list, max_length=50)
    caused_by: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_reading_ids(self):
        _validate_twin_event_refs(self.caused_by)
        ids = self.reading_ids or ([self.reading_id] if self.reading_id else [])
        if not ids or any(not item for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("provide unique reading_id or reading_ids")
        if self.reading_id and self.reading_ids and self.reading_id not in self.reading_ids:
            raise ValueError("reading_id must be included in reading_ids")
        return self


class ContainmentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=200)
    caused_by: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_twin_event_refs(self):
        _validate_twin_event_refs(self.caused_by)
        return self


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sensor_type: SensorType | None = None
    value: FiniteFloat | None = None


class AdvisoryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    domain: Literal["traffic", "water", "power", "air_quality", "emergency"]
    value: FiniteFloat | None
    z_score: FiniteFloat
    rate_of_change: FiniteFloat
    out_of_bounds: FiniteFloat
    correlation_strength: FiniteFloat
    incident_claimed: FiniteFloat
    decayed_flags: FiniteFloat
    baseline_dev_norm: FiniteFloat
    flat_run_len: FiniteFloat


class TwinEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["readings"]
    data: dict


class ActionAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    reading_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    parameters: dict
    targets: list[str] = Field(default_factory=list, max_length=128)
    reading_ids: list[str] = Field(default_factory=list, max_length=128)
    idempotency_key: str = Field(default="", max_length=256)
    risk_level: Literal["R1", "R2", "R3", "NONE"]
    domain: str | None = None


class TokenVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=8192)
    action: str = Field(min_length=1, max_length=128)
    parameters: dict
    targets: list[str] | None = None
    idempotency_key: str | None = None


class RollbackPoolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    reading_id: str = Field(min_length=1, max_length=128)


class TrustVerdictToolOutput(BaseModel):
    trust_score: FiniteFloat
    state: Literal["Trusted", "Degraded", "Untrusted"]
    reasons: list[str]
    caused_by: str
    scale: list[float]
    cutoffs: dict[str, float]
    history_requirement: dict[str, int]


class PendingTrustVerdictToolOutput(BaseModel):
    status: Literal["pending"]
    reading_id: str
    retry_after_ms: int
    last_scored_tick: int


class AuthorizationToolOutput(BaseModel):
    decision: Literal["approved", "refused"]
    token: str | None = None
    token_id: str | None = None
    refusal_code: str | None = None
    expires_at: FiniteFloat | None = None


class TokenVerificationToolOutput(BaseModel):
    verified: bool
    token_id: str | None = None
    refusal_code: str | None = None


mcp_app = mcp_server.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    host="127.0.0.1",
)


@asynccontextmanager
async def lifespan(_app):
    # Mounted Starlette applications do not receive lifespan startup
    # automatically, so initialize the MCP transport in the parent app.
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(
    title="Guardian Layer — Unified Mock",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def structured_authorization_field_errors(request, exc: RequestValidationError):
    if request.url.path != "/api/actions/authorize":
        return await request_validation_exception_handler(request, exc)
    accepted_names = {
        "risk": "risk_level",
        "source_reading_ids": "reading_ids",
    }
    missing_fields = []
    unknown_fields = []
    invalid_fields = []
    for error in exc.errors():
        location = error.get("loc", ())
        field = str(location[-1]) if location else "request"
        entry = {"field": field, "accepted_name": field}
        if error.get("type") == "missing":
            missing_fields.append(entry)
        elif error.get("type") == "extra_forbidden":
            unknown_fields.append({"field": field, "accepted_name": accepted_names.get(field)})
        else:
            invalid_fields.append(entry)
    return JSONResponse({
        "error": "invalid_authorize_action_request",
        "missing_fields": missing_fields,
        "unknown_fields": unknown_fields,
        "invalid_fields": invalid_fields,
    }, status_code=422)


@app.middleware("http")
async def protect_brain_mcp(request, call_next):
    try:
        max_bytes = int(os.environ.get("GUARDIAN_MAX_REQUEST_BYTES", "1048576"))
    except ValueError:
        return JSONResponse({"detail": "invalid_request_size_configuration"}, status_code=503)
    if max_bytes < 1:
        return JSONResponse({"detail": "invalid_request_size_configuration"}, status_code=503)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return JSONResponse({"detail": "request_body_too_large"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "invalid_content_length"}, status_code=400)
    if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
        if os.environ.get("DEMO_MODE", "false").casefold() not in {"1", "true", "yes"}:
            expected = os.environ.get("GUARDIAN_BRAIN_MCP_BEARER_KEY", "")
            supplied = request.headers.get("authorization", "")
            if not expected:
                return JSONResponse({"detail": "guardian_brain_mcp_auth_not_configured"}, status_code=503)
            if not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], expected):
                return JSONResponse({"detail": "invalid_brain_bearer_key"}, status_code=401)
    return await call_next(request)

_action_policy = ActionPolicy()
_audit_log = JsonlAuditLog()
_latest_twin_sim_time: float | None = None
_latest_twin_run_id: str | None = None
_twin_delivery_cache: dict[tuple[str, str], str] = {}
_last_tick_by_run: dict[str, int] = {}
_twin_discovery_by_run: dict[str, dict[str, Any]] = {}


def _twin_sim_clock() -> float:
    try:
        settings = GuardianSettings.from_env()
        value = read_twin_clock_sync(timeout_seconds=settings.twin_mcp_timeout_seconds)
        return _clock_from_discovery({"get_clock": value})
    except (TwinDiscoveryError, ValueError) as exc:
        raise TokenError("twin_sim_clock_unavailable") from exc


_token_service = ActionTokenService.from_env(clock=_twin_sim_clock)


def _require_integration_key(authorization: str | None) -> None:
    if os.environ.get("DEMO_MODE", "false").casefold() in {"1", "true", "yes"}:
        return
    expected = os.environ.get("GUARDIAN_API_BEARER_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="guardian_api_auth_not_configured")
    supplied = authorization or ""
    if not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], expected):
        raise HTTPException(status_code=401, detail="invalid_bearer_key")


@app.get("/health")
@app.get("/api/health")
def health():
    available = load_model() is not None
    from app import _model_error
    return {
        "status": "ok",
        "guardian_status": "ready",
        "model_available": available,
        "model_error": _model_error,
        "model_version": METADATA.get("model_version", "unknown"),
        "time": time.time(),
    }


@app.get("/api/overview")
def overview():
    return service.overview()


@app.get("/api/scenarios")
def scenarios():
    return scenario_catalog()


@app.get("/api/capabilities")
def capabilities():
    result = describe_capabilities().model_dump(mode="json")
    public = _token_service.public_key
    result["action_token"] = {
        "version": 1,
        "kid": _token_service.kid,
        "public_key_pem": (public.public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii") if public else None),
    }
    result["action_capacity"] = {
        "source": _action_policy.capacity_source,
        "power_action_cap": _action_policy.power_cap,
        "power_action_scope": _action_policy.power_action_scope,
        "rollback_pool_sizes": _action_policy.pool_sizes,
    }
    trust_policy = service.trust_policy
    result["guardian_verdict_policy"] = {
        "states": TRUST_STATE_MAP,
        "scale": [0.0, 1.0],
        "trusted_min_inclusive": trust_policy.trusted_min,
        "degraded_min_exclusive": trust_policy.suspect_min,
        "risk_minimums": trust_policy.risk_minimums,
        "risk_values_provisional": trust_policy.risk_values_provisional,
    }
    result["supported_actions"] = sorted(_action_policy.allowlist)
    result["action_aliases"] = dict(_action_policy.aliases)
    return result


@app.post("/api/advisory")
def evaluate_advisory(request: AdvisoryRequest):
    try:
        return predict_reading(request.model_dump()).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Model evaluation failed: {type(exc).__name__}: {exc}") from exc


@app.get("/api/timeline")
def timeline(limit: int = 100):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    return {"events": service.timeline_snapshot(limit)}


@app.get("/api/evaluations")
def evaluations(limit: int = 50):
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    return {"evaluations": service.evaluations[-limit:]}


@app.post("/api/reset")
def reset_demo(authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    global _latest_twin_sim_time, _latest_twin_run_id
    service.reset()
    if _latest_twin_run_id is not None:
        _action_policy.reset_run(_latest_twin_run_id)
    _latest_twin_sim_time, _latest_twin_run_id = None, None
    _twin_delivery_cache.clear()
    _last_tick_by_run.clear()
    _twin_discovery_by_run.clear()
    return {"status": "reset", "overview": service.overview()}


@app.post("/api/simulations/{scenario_id}")
def simulate(scenario_id: str, request: SimulationRequest | None = Body(default=None),
             authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    request = request or SimulationRequest()
    try:
        result = run_scenario(
            service,
            scenario_id,
            sensor_type=request.sensor_type,
            value=request.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "overview": service.overview()}


@app.post("/ingest")
def ingest(request: IngestRequest, authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    payload = request.model_dump()
    payload["require_signature"] = GuardianSettings().require_reading_signatures
    result = service.process_reading(payload)
    if result["layer_a"]["status"] == "failed":
        reason = result.get("rejection_reason", "security_rejection")
        status_code = 401 if reason == "invalid_signature" else 409
        return JSONResponse(
            status_code=status_code,
            content={"detail": reason, "reading_id": result["reading_id"], "evaluation": result},
        )
    verdict = result["guardian"]
    return {"reading_id": result["reading_id"], "verdict": verdict, "evaluation": result}


@app.post("/api/integrations/twin/event")
def ingest_twin_event(request: TwinEventRequest, authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    run_id = request.data.get("run_id")
    readings = request.data.get("readings")
    if (not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", run_id)
            or not isinstance(readings, list)):
        raise HTTPException(status_code=422, detail="readings event requires run_id and readings array")
    global _latest_twin_run_id, _latest_twin_sim_time
    if _latest_twin_run_id is not None and run_id != _latest_twin_run_id:
        _action_policy.reset_run(_latest_twin_run_id)
        service.reset()
        _latest_twin_sim_time = None
        _twin_delivery_cache.clear()
        _last_tick_by_run.clear()
        _twin_discovery_by_run.clear()
    _latest_twin_run_id = run_id
    settings = GuardianSettings()
    if settings.twin_base_url and settings.twin_bearer_key and run_id not in _twin_discovery_by_run:
        try:
            _ensure_twin_discovery(run_id)
        except HTTPException:
            # Trust scoring remains independent; authorization will fail closed.
            _twin_discovery_by_run[run_id] = {"_error": "twin_discovery_unavailable"}
    results = []
    skipped = []
    duplicates = []
    # Evaluate emergency observations last so same-tick neighbours are available.
    ordered_readings = sorted(readings, key=lambda v: isinstance(v, dict) and v.get("sensor") == "emergency_calls")
    for item in ordered_readings:
        try:
            if not isinstance(item, dict) or item.get("run_id") != run_id:
                raise ValueError("reading run_id must match its event envelope")
            payload = normalize_twin_reading(item)
            delivery_key = (run_id, payload["reading_id"])
            fingerprint_fields = ("run_id", "reading_id", "device_id", "node_id", "timestamp", "tick",
                                  "sensor", "channel", "value", "unit", "lat", "lon")
            fingerprint = hashlib.sha256(json.dumps({k: item.get(k) for k in fingerprint_fields},
                sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
            previous = _twin_delivery_cache.get(delivery_key)
            if previous is not None:
                if previous == fingerprint:
                    duplicates.append(payload["reading_id"])
                    service._event("duplicate_delivery", payload["reading_id"], {"run_id": run_id})
                    _audit_log.record(run_id=run_id, event_type="duplicate_delivery",
                        reading_id=payload["reading_id"], trust_score=None, verdict=None, action=None,
                        decision="ignored", reason=None, caused_by=payload["reading_id"],
                        data={"idempotency_key": payload["reading_id"]})
                    continue
                raise ValueError("replay_attack_reading_id_content_mismatch")
            last_tick = _last_tick_by_run.get(run_id)
            tolerance = int(os.environ.get("TWIN_REPLAY_TICK_TOLERANCE", "100"))
            if tolerance < 0:
                raise ValueError("TWIN_REPLAY_TICK_TOLERANCE must be non-negative")
            tick = int(payload["sequence_number"])
            if last_tick is not None and tick < last_tick - tolerance:
                raise ValueError("replay_attack_tick_too_far_behind")
            evaluation = service.process_reading(payload)
            if evaluation.get("layer_a", {}).get("status") == "passed":
                _twin_delivery_cache[delivery_key] = fingerprint
                if len(_twin_delivery_cache) > 100_000:
                    _twin_delivery_cache.pop(next(iter(_twin_delivery_cache)))
                if last_tick is not None and tick > last_tick + 1:
                    service._event("tick_gap", payload["reading_id"], {
                        "run_id": run_id, "previous_tick": last_tick, "tick": tick,
                        "skipped_ticks": tick - last_tick - 1,
                    })
                    _audit_log.record(run_id=run_id, event_type="tick_gap",
                        reading_id=payload["reading_id"], trust_score=None, verdict=None,
                        action=None, decision="observed", reason="ticks_skipped",
                        caused_by=payload["reading_id"], data={"previous_tick": last_tick, "tick": tick})
                _last_tick_by_run[run_id] = max(last_tick if last_tick is not None else tick, tick)
                _latest_twin_sim_time = max(_latest_twin_sim_time or payload["timestamp"], payload["timestamp"])
            verdict = evaluation.get("guardian") or {}
            _audit_log.record(run_id=run_id, event_type="reading_evaluated",
                reading_id=payload["reading_id"], trust_score=verdict.get("trust_score"),
                verdict=verdict.get("verdict"), action=None,
                decision="denied" if evaluation.get("action_blocked") else "evaluated",
                reason=evaluation.get("rejection_reason"), caused_by=payload["reading_id"],
                data={"sensor_id": payload["sensor_id"], "sequence_number": payload["sequence_number"]})
            results.append({"reading_id": payload["reading_id"], "evaluation": evaluation})
        except (ValueError, TypeError, KeyError) as exc:
            skipped.append({"reading_id": item.get("reading_id") if isinstance(item, dict) else None,
                            "reason": str(exc)})
    return {"run_id": run_id, "processed": len(results), "duplicates": duplicates,
            "skipped": skipped, "results": results,
            "twin_discovery": ("available" if run_id in _twin_discovery_by_run
                and "_error" not in _twin_discovery_by_run[run_id] else "unavailable_or_not_configured")}


def _fresh_verdict(reading_id: str):
    reading = service.buffer.get_reading(reading_id)
    if reading is None or service.buffer.is_invalid(reading_id):
        raise HTTPException(status_code=409, detail="fresh_verdict_evidence_unavailable")
    evaluation = next((e for e in reversed(service.evaluations) if e["reading_id"] == reading_id), None)
    from guardian.scoring import compute_trust_score
    with service._lock:
        history_before = [item for item in service.buffer.history(reading.sensor_id)
                          if item.sequence_number < reading.sequence_number]
        reputation_change = (evaluation or {}).get("reputation_change", {})
        baseline_flags = reputation_change.get("decayed_flags_before")

        class HistoricalBuffer:
            def history(self, sensor_id: str, include_invalid: bool = False):
                history = service.buffer.history(sensor_id, include_invalid=include_invalid)
                if sensor_id == reading.sensor_id:
                    history = [item for item in history if item.sequence_number < reading.sequence_number]
                return history

            def __getattr__(self, name):
                return getattr(service.buffer, name)

        class BaselineReputation:
            def recent_flags(self, sensor_id: str, now: float | None = None):
                if sensor_id == reading.sensor_id and baseline_flags is not None:
                    return baseline_flags
                return service.reputation.recent_flags(sensor_id, now)

            def __getattr__(self, name):
                return getattr(service.reputation, name)

        verdict = compute_trust_score(reading, HistoricalBuffer(), BaselineReputation(),
            incident_type=(evaluation or {}).get("incident_type"),
            trusted_threshold=service.trust_policy.trusted_min,
            suspect_threshold=service.trust_policy.suspect_min,
            record_reputation=False)
        if len(history_before) < MIN_HISTORY_FOR_STATISTICAL_DRIFT:
            verdict.reasons.append("insufficient_history")
        return verdict


def _last_scored_tick(sensor_id: str) -> int:
    scored_ticks = []
    for reading_id, verdict in service.verdict_log.items():
        if verdict.sensor_id != sensor_id:
            continue
        scored_reading = service.buffer.get_reading(reading_id)
        if scored_reading is not None:
            scored_ticks.append(scored_reading.sequence_number)
    return max(scored_ticks, default=0)


def _pending_verdict(reading_id: str, sensor_id: str) -> dict[str, Any]:
    return {
        "status": "pending",
        "reading_id": reading_id,
        "retry_after_ms": GuardianSettings.from_env().verdict_retry_after_ms,
        "last_scored_tick": _last_scored_tick(sensor_id),
    }


def _history_requirement_for(reading) -> dict[str, int]:
    available = sum(
        item.sequence_number < reading.sequence_number
        for item in service.buffer.history(reading.sensor_id)
    )
    return {
        "minimum_history_readings": MIN_HISTORY_FOR_STATISTICAL_DRIFT,
        "available_history_readings": available,
    }


def _ensure_twin_discovery(run_id: str) -> dict[str, Any]:
    if run_id in _twin_discovery_by_run:
        cached = _twin_discovery_by_run[run_id]
        if "_error" in cached:
            raise HTTPException(status_code=503, detail="twin_discovery_unavailable")
        return cached
    try:
        snapshot = discover_twin_sync(timeout_seconds=GuardianSettings.from_env().twin_mcp_timeout_seconds)
    except (TwinDiscoveryError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="twin_discovery_unavailable") from exc
    _twin_discovery_by_run[run_id] = snapshot
    capacities = snapshot.get("discovered_capacities")
    if capacities:
        power = capacities.get("Power", capacities.get("power", {}))
        rollback = {domain: caps.get("rollback_pool_size") for domain, caps in capacities.items()
                    if isinstance(caps, dict) and isinstance(caps.get("rollback_pool_size"), int)}
        normalized = {}
        if isinstance(power, dict) and isinstance(power.get("action_cap"), int):
            normalized["power_action_cap"] = power["action_cap"]
        if rollback:
            normalized["rollback_pool_sizes"] = rollback
        if normalized:
            _action_policy.apply_discovered_capacity(normalized)
    return snapshot


def _clock_from_discovery(snapshot: dict[str, Any]) -> float:
    value = snapshot.get("get_clock")
    if isinstance(value, dict):
        for key in ("simulated_time", "sim_time", "timestamp", "time"):
            candidate = value.get(key)
            if (isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
                    and math.isfinite(candidate)):
                return float(candidate)
            if isinstance(candidate, str):
                from datetime import datetime
                try:
                    parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
                    if parsed.utcoffset() is not None and math.isfinite(parsed.timestamp()):
                        return parsed.timestamp()
                except (OverflowError, ValueError):
                    continue
    raise TokenError("twin_sim_clock_unavailable")


def _refresh_twin_sim_clock() -> float:
    try:
        settings = GuardianSettings.from_env()
        value = read_twin_clock_sync(timeout_seconds=settings.twin_mcp_timeout_seconds)
        now = _clock_from_discovery({"get_clock": value})
    except (TwinDiscoveryError, ValueError) as exc:
        raise TokenError("twin_sim_clock_unavailable") from exc
    _token_service.clock = lambda: now
    return now


def _twin_manifest_actions(manifest: dict[str, Any]) -> set[str]:
    actions = manifest.get("list_actions")
    if isinstance(actions, dict):
        actions = actions.get("actions", actions.get("result"))
    if not isinstance(actions, list):
        return set()
    names = set()
    for item in actions:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("action")
            if not isinstance(name, str) or not name:
                name = item.get("name")
        else:
            continue
        if isinstance(name, str) and name:
            names.add(_action_policy.aliases.get(name, name))
    return names


def _twin_action_info(manifest: dict[str, Any], action: str) -> dict[str, Any] | None:
    actions = manifest.get("list_actions")
    if isinstance(actions, dict):
        actions = actions.get("actions", actions.get("result"))
    if not isinstance(actions, list):
        return None
    for item in actions:
        if not isinstance(item, dict):
            continue
        name = item.get("action") or item.get("name")
        if isinstance(name, str) and _action_policy.aliases.get(name, name) == action:
            return item
    return None


def _dispatch_carrier(action_info: dict[str, Any], manifest: dict[str, Any]) -> str | None:
    targets = action_info.get("target_nodes")
    if isinstance(targets, list):
        carriers = sorted({target for target in targets if isinstance(target, str) and target})
    else:
        carriers = []
    if not carriers:
        nodes_result = manifest.get("list_nodes")
        nodes = nodes_result.get("nodes") if isinstance(nodes_result, dict) else None
        if isinstance(nodes, list):
            carriers = sorted({
                node.get("node_id") for node in nodes
                if isinstance(node, dict) and node.get("role") == "dispatch_center"
                and "dispatch" in (node.get("actuators") or [])
                and isinstance(node.get("node_id"), str)
            })
    return carriers[0] if len(carriers) == 1 else None


def _validate_dispatch_evidence(request: ActionAuthorizationRequest, reading_ids: list[str],
                                action_info: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Bind an ambulance dispatch token to current medical and ambulance-capacity evidence."""
    if request.risk_level != "R2" or (request.domain or "").casefold() != "emergency":
        raise HTTPException(status_code=403, detail="dispatch_contract_mismatch")
    if action_info.get("risk") != "R2" or str(action_info.get("domain", "")).casefold() != "emergency":
        raise HTTPException(status_code=409, detail="dispatch_contract_mismatch")
    if action_info.get("preview_required") is not False:
        raise HTTPException(status_code=409, detail="dispatch_preview_contract_mismatch")
    if request.parameters.get("unit_type") != "ambulance":
        raise HTTPException(status_code=403, detail="dispatch_unit_type_mismatch")
    units = request.parameters.get("units")
    if isinstance(units, bool) or not isinstance(units, int) or units != 1:
        raise HTTPException(status_code=403, detail="invalid_dispatch_units")

    carrier = _dispatch_carrier(action_info, manifest)
    if carrier is None or request.targets != [carrier]:
        raise HTTPException(status_code=403, detail="dispatch_carrier_mismatch")

    evaluations = {
        evaluation.get("reading_id"): evaluation
        for evaluation in service.evaluations
        if isinstance(evaluation, dict) and evaluation.get("reading_id") in reading_ids
    }
    bound = [evaluations.get(reading_id) for reading_id in reading_ids]
    primary = evaluations.get(request.reading_id) or {}
    primary_original = primary.get("original_reading") or {}
    if primary.get("sensor_type") != "emergency_call" or primary_original.get("channel") != "medical":
        raise HTTPException(status_code=409, detail="primary_medical_incident_evidence_required")
    medical = []
    capacity = []
    for evaluation in bound:
        if not isinstance(evaluation, dict):
            continue
        original = evaluation.get("original_reading") or {}
        if (evaluation.get("sensor_type") == "emergency_call"
                and original.get("channel") == "medical"
                and isinstance(original.get("node_id"), str)):
            medical.append(evaluation)
        if (evaluation.get("sensor_type") == "units_free"
                and original.get("channel") == "ambulance"
                and original.get("unit") == "units"
                and original.get("node_id") == carrier):
            capacity.append(evaluation)
    if not medical:
        raise HTTPException(status_code=409, detail="medical_incident_evidence_required")
    destination = request.parameters.get("destination")
    if not isinstance(destination, str) or destination != primary_original.get("node_id"):
        raise HTTPException(status_code=403, detail="dispatch_destination_mismatch")
    if not capacity:
        raise HTTPException(status_code=409, detail="ambulance_capacity_evidence_required")

    try:
        current = call_twin_tool_sync("get_readings", {"node_id": carrier, "sensor": "units_free"})
    except TwinDiscoveryError as exc:
        raise HTTPException(status_code=503, detail="twin_current_capacity_unavailable") from exc
    if not isinstance(current, dict) or current.get("run_id") != request.run_id:
        raise HTTPException(status_code=503, detail="twin_current_capacity_unavailable")
    current_readings = current.get("readings")
    if not isinstance(current_readings, list):
        raise HTTPException(status_code=503, detail="twin_current_capacity_unavailable")
    current_ambulance = next((item for item in current_readings
        if isinstance(item, dict) and item.get("sensor") == "units_free"
        and item.get("channel") == "ambulance" and item.get("node_id") == carrier
        and item.get("unit") == "units"), None)
    if current_ambulance is None:
        raise HTTPException(status_code=503, detail="twin_current_capacity_unavailable")
    current_value = current_ambulance.get("value")
    current_id = current_ambulance.get("reading_id")
    if not isinstance(current_id, str) or not current_id:
        raise HTTPException(status_code=503, detail="twin_current_capacity_unavailable")
    current_tick = current.get("tick")
    reported_tick = current_ambulance.get("tick")
    if current_tick is not None and (isinstance(current_tick, bool) or not isinstance(current_tick, int)):
        raise HTTPException(status_code=503, detail="twin_current_capacity_unavailable")
    if current_tick is not None and (isinstance(reported_tick, bool) or not isinstance(reported_tick, int)):
        raise HTTPException(status_code=503, detail="twin_current_capacity_unavailable")
    if (isinstance(current_tick, int) and not isinstance(current_tick, bool)
            and isinstance(reported_tick, int) and not isinstance(reported_tick, bool)
            and current_tick - reported_tick not in {0, 1}):
        raise HTTPException(status_code=409, detail="ambulance_capacity_evidence_not_current")
    matching_evidence = []
    for evaluation in capacity:
        original = evaluation.get("original_reading") or {}
        evidence_tick = original.get("sequence_number")
        if (evaluation.get("reading_id") == current_id
                or (isinstance(current_tick, int) and not isinstance(current_tick, bool)
                    and isinstance(evidence_tick, int) and not isinstance(evidence_tick, bool)
                    and current_tick - evidence_tick == 1)):
            if (isinstance(original.get("value"), (int, float))
                    and not isinstance(original.get("value"), bool)
                    and original.get("value") == current_value):
                matching_evidence.append(evaluation)
    if not matching_evidence:
        raise HTTPException(status_code=409, detail="ambulance_capacity_evidence_not_current")
    if (isinstance(current_value, bool) or not isinstance(current_value, (int, float))
            or current_value < units):
        raise HTTPException(status_code=409, detail="insufficient_ambulance_capacity")


@app.post("/api/actions/authorize")
def authorize_action(request: ActionAuthorizationRequest, authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    if _latest_twin_run_id is None or request.run_id != _latest_twin_run_id:
        raise HTTPException(status_code=409, detail="authorization_run_id_mismatch")
    bound_reading_ids = request.reading_ids or [request.reading_id]
    if any(service.buffer.is_invalid(rid) for rid in bound_reading_ids):
        raise HTTPException(status_code=409, detail="reading_invalidated")
    if request.reading_id not in bound_reading_ids or any(rid not in service.verdict_log for rid in bound_reading_ids):
        raise HTTPException(status_code=409, detail="authorization_reading_ids_unavailable")
    verdict = service.verdict_log.get(request.reading_id)
    if verdict is None:
        _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
            trust_score=None, verdict=None, action=request.action, decision="denied",
            reason="verdict_not_found", caused_by=request.reading_id,
            data={"idempotency_key": request.idempotency_key} if request.idempotency_key else {})
        raise HTTPException(status_code=404, detail="verdict_not_found")
    fresh_verdicts = [_fresh_verdict(rid) for rid in bound_reading_ids]
    verdict = fresh_verdicts[0]
    verdict.trust_score = min(v.trust_score for v in fresh_verdicts)
    evaluated = next((e for e in reversed(service.evaluations) if e["reading_id"] == request.reading_id), None)
    sensor_domain = {
        "traffic_cam": "Traffic", "water_level": "Water", "power_load": "Power",
        "air_quality": "Air Quality", "emergency_call": "Emergency", "units_free": "Emergency",
    }.get(evaluated["sensor_type"] if evaluated else "")
    if sensor_domain is None or (request.domain or "").casefold() != sensor_domain.casefold():
        try:
            denied_action = _action_policy.normalize(request.action)
        except ActionPolicyError:
            denied_action = request.action
        _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
            trust_score=verdict.trust_score, verdict=verdict.verdict, action=denied_action,
            decision="denied", reason="reading_domain_mismatch_or_unsupported_domain",
            caused_by=request.reading_id,
            data={"idempotency_key": request.idempotency_key} if request.idempotency_key else {})
        raise HTTPException(status_code=403, detail="reading_domain_mismatch_or_unsupported_domain")
    normalized = request.action
    try:
        if _token_service.private_key is None:
            raise TokenError("signing_key_unavailable")
        manifest = _ensure_twin_discovery(request.run_id)
        manifest_action = _action_policy.aliases.get(request.action, request.action)
        if manifest_action not in _twin_manifest_actions(manifest):
            raise ActionPolicyError("action_not_in_twin_manifest")
        normalized = _action_policy.normalize(request.action)
        action_info = _twin_action_info(manifest, normalized)
        if normalized == "set_valve_position":
            action_list = manifest.get("list_actions")
            preview_enforced = action_list.get("preview_enforced") if isinstance(action_list, dict) else False
            # Twin scopes preview state to its caller. In twin-mock-3 only the
            # Brain caller can preview; Twin enforces freshness and one-commit
            # use when Brain submits the exact command with this token.
            if (action_info is None or action_info.get("preview_required") is not True
                    or preview_enforced is not True):
                raise ActionPolicyError("safe_preview_tool_unconfirmed")
            if action_info.get("risk") != request.risk_level or str(action_info.get("domain", "")).casefold() != "water":
                raise ActionPolicyError("twin_action_contract_mismatch")
            allowed_targets = action_info.get("target_nodes")
            if request.parameters != {"position": 40}:
                raise ActionPolicyError("twin_action_contract_mismatch")
            if (request.targets != ["WAT-01"] or not isinstance(allowed_targets, list)
                    or "WAT-01" not in allowed_targets):
                raise ActionPolicyError("target_not_in_twin_manifest")
        elif normalized == "set_grid_switch":
            raise ActionPolicyError("safe_preview_tool_unconfirmed")
        elif normalized == "dispatch":
            if action_info is None:
                raise ActionPolicyError("action_not_in_twin_manifest")
            _validate_dispatch_evidence(request, bound_reading_ids, action_info, manifest)
        state = manifest.get("get_containment_state")
        if isinstance(state, dict):
            quarantined = {item for item in state.get("quarantined", []) if isinstance(item, str)}
            devices = state.get("devices", [])
            if isinstance(devices, list):
                for item in devices:
                    if isinstance(item, dict) and item.get("state") == "quarantined":
                        quarantined.update(value for value in
                            (item.get("device_id"), item.get("node_id")) if isinstance(value, str))
            if set(request.targets) & quarantined:
                raise ActionPolicyError("DEVICE_QUARANTINED")
        normalized, _ = _action_policy.authorize(run_id=request.run_id, action=request.action,
            parameters=request.parameters, trust_score=verdict.trust_score,
            risk_level=request.risk_level, domain=request.domain)
        _refresh_twin_sim_clock()
        token, claims = _token_service.issue(run_id=request.run_id, action=normalized,
            parameters=request.parameters, reading_id=request.reading_id,
            trust_score=verdict.trust_score, risk_level=request.risk_level,
            targets=request.targets, reading_ids=bound_reading_ids,
            idempotency_key=request.idempotency_key)
    except HTTPException as exc:
        reason = str(exc.detail)
        _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
            trust_score=verdict.trust_score, verdict=verdict.verdict, action=normalized,
            decision="denied", reason=reason, caused_by=request.reading_id,
            data={"idempotency_key": request.idempotency_key} if request.idempotency_key else {})
        raise
    except ActionPolicyError as exc:
        reason = str(exc)
        _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
            trust_score=verdict.trust_score, verdict=verdict.verdict, action=normalized,
            decision="denied", reason=reason, caused_by=request.reading_id,
            data={"idempotency_key": request.idempotency_key} if request.idempotency_key else {})
        raise HTTPException(status_code=409 if reason in {"safe_preview_tool_unconfirmed", "DEVICE_QUARANTINED"}
                            else 403, detail=reason) from exc
    except TokenError as exc:
        reason = str(exc)
        _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
            trust_score=verdict.trust_score, verdict=verdict.verdict, action=normalized,
            decision="denied", reason=reason, caused_by=request.reading_id,
            data={"idempotency_key": request.idempotency_key} if request.idempotency_key else {})
        raise HTTPException(status_code=503, detail=reason) from exc
    except (TwinDiscoveryError, ValueError) as exc:
        reason = "twin_discovery_unavailable"
        _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
            trust_score=verdict.trust_score, verdict=verdict.verdict, action=normalized,
            decision="denied", reason=reason, caused_by=request.reading_id,
            data={"idempotency_key": request.idempotency_key} if request.idempotency_key else {})
        raise HTTPException(status_code=503, detail=reason) from exc
    _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
        trust_score=verdict.trust_score, verdict=verdict.verdict, action=normalized,
        decision="approved", reason=None, caused_by=request.reading_id,
        data={"token_id": claims["token_id"], "idempotency_key": request.idempotency_key})
    return {"decision": "approved", "reading_id": request.reading_id,
            "action": normalized, "token": token, "token_id": claims["token_id"], "expires_at": claims["exp"]}


@app.post("/api/actions/verify")
def verify_action_token(request: TokenVerifyRequest, authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    try:
        if _latest_twin_run_id is not None:
            _refresh_twin_sim_clock()
        else:
            _token_service.clock = _twin_sim_clock
        normalized = _action_policy.normalize(request.action)
        claims = _token_service.verify(request.token, action=normalized, parameters=request.parameters,
            targets=request.targets, idempotency_key=request.idempotency_key)
    except (TokenError, ActionPolicyError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"verified": True, "token_id": claims["token_id"], "run_id": claims["run_id"],
            "reading_ids": claims["reading_ids"], "expires_at": claims["exp"]}


@mcp_server.tool(name=MCP_TOOL_GET_TRUST_VERDICT, title="Get Guardian trust verdict", structured_output=True)
def brain_get_trust_verdict(reading_id: str, fresh: bool = False) -> TrustVerdictToolOutput | PendingTrustVerdictToolOutput:
    """Return the deterministic verdict; fresh rechecks current neighbour evidence without adding flags."""
    reading = service.buffer.get_reading(reading_id)
    if reading is None:
        raise ValueError("verdict_not_found")
    if service.buffer.is_invalid(reading_id):
        raise ValueError("reading_invalidated")
    verdict = service.verdict_log.get(reading_id)
    last_scored_tick = _last_scored_tick(reading.sensor_id)
    if verdict is None or reading.sequence_number > last_scored_tick:
        return PendingTrustVerdictToolOutput(**_pending_verdict(reading_id, reading.sensor_id))
    if fresh:
        verdict = _fresh_verdict(reading_id)
    policy = service.trust_policy
    return TrustVerdictToolOutput(trust_score=verdict.trust_score,
        state=TRUST_STATE_MAP[verdict.verdict], reasons=verdict.reasons, caused_by=reading_id,
        scale=[0.0, 1.0], cutoffs={"trusted_min_inclusive": policy.trusted_min,
            "degraded_min_exclusive": policy.suspect_min},
        history_requirement=_history_requirement_for(reading))


@mcp_server.tool(name=MCP_TOOL_AUTHORIZE_ACTION, title="Authorize Guardian action", structured_output=True)
def brain_authorize_action(run_id: str, reading_ids: list[str], action: str, targets: list[str],
                           params: dict[str, Any], risk_level: Literal["R1", "R2", "R3", "NONE"],
                           domain: str, idempotency_key: str) -> AuthorizationToolOutput:
    """Issue an action token by calling the same authorization service used by HTTP."""
    if not reading_ids or not idempotency_key:
        return AuthorizationToolOutput(decision="refused", refusal_code="reading_ids_and_idempotency_key_required")
    internal_api_key = os.environ.get("GUARDIAN_API_BEARER_KEY", "")
    try:
        request = ActionAuthorizationRequest(run_id=run_id, reading_id=reading_ids[0],
            action=action, parameters=params, targets=targets, reading_ids=reading_ids,
            idempotency_key=idempotency_key, risk_level=risk_level, domain=domain)
        result = authorize_action(request, authorization=f"Bearer {internal_api_key}")
        return AuthorizationToolOutput(decision="approved", token=result["token"],
            token_id=result["token_id"], expires_at=result["expires_at"])
    except (HTTPException, ValueError, TypeError) as exc:
        code = exc.detail if isinstance(exc, HTTPException) else "invalid_authorization_request"
        return AuthorizationToolOutput(decision="refused", refusal_code=str(code))


def brain_verify_action_token(token: str, action: str, targets: list[str], params: dict[str, Any],
                              idempotency_key: str) -> TokenVerificationToolOutput:
    """Test-only verifier; disabled unless GUARDIAN_ENABLE_TEST_TOKEN_VERIFY is true."""
    if os.environ.get("GUARDIAN_ENABLE_TEST_TOKEN_VERIFY", "false").casefold() not in {"1", "true", "yes"}:
        return TokenVerificationToolOutput(verified=False, refusal_code="test_verification_disabled")
    try:
        normalized = _action_policy.normalize(action)
        claims = _token_service.verify(token, action=normalized, parameters=params,
            targets=targets, idempotency_key=idempotency_key)
        return TokenVerificationToolOutput(verified=True, token_id=claims["token_id"])
    except (TokenError, ActionPolicyError) as exc:
        return TokenVerificationToolOutput(verified=False, refusal_code=str(exc))


if os.environ.get("GUARDIAN_ENABLE_TEST_TOKEN_VERIFY", "false").casefold() in {"1", "true", "yes"}:
    mcp_server.tool(name=MCP_TOOL_VERIFY_ACTION_TOKEN,
        title="Verify Guardian action token (test only)", structured_output=True)(brain_verify_action_token)


@app.post("/api/actions/rollback-pool/{domain}/{node_id}")
def rollback_pool(domain: str, node_id: str, request: RollbackPoolRequest, release: bool = False,
                  authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    if request.reading_id not in service.verdict_log:
        _audit_log.record(run_id=request.run_id, event_type="rollback_pool_decision",
            reading_id=request.reading_id, trust_score=None, verdict=None, action="rollback_reading",
            decision="denied", reason="verdict_not_found", caused_by=request.reading_id,
            data={"domain": domain, "node_id": node_id})
        raise HTTPException(status_code=404, detail="verdict_not_found")
    try:
        in_use = (_action_policy.release_rollback(domain, node_id) if release
                  else _action_policy.reserve_rollback(domain, node_id))
    except ActionPolicyError as exc:
        _audit_log.record(run_id=request.run_id, event_type="rollback_pool_decision",
            reading_id=request.reading_id, trust_score=None, verdict=None, action="rollback_reading",
            decision="denied", reason=str(exc), caused_by=request.reading_id,
            data={"domain": domain, "node_id": node_id})
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit_log.record(run_id=request.run_id, event_type="rollback_pool_decision",
        reading_id=request.reading_id, trust_score=None, verdict=None, action="rollback_reading",
        decision="released" if release else "reserved", reason=None, caused_by=request.reading_id,
        data={"domain": domain, "node_id": node_id, "in_use": in_use})
    return {"status": "released" if release else "reserved", "domain": domain,
            "node_id": node_id, "in_use": in_use}


@app.get("/trust_verdict/{sensor_id}/{reading_id}")
def get_trust_verdict(sensor_id: str, reading_id: str):
    reading = service.buffer.get_reading(reading_id)
    verdict = service.verdict_log.get(reading_id)
    if reading is None or reading.sensor_id != sensor_id:
        raise HTTPException(status_code=404, detail="verdict_not_found")
    last_scored_tick = _last_scored_tick(sensor_id)
    if verdict is None or reading.sequence_number > last_scored_tick:
        return _pending_verdict(reading_id, sensor_id)
    result = verdict.to_dict()
    result["history_requirement"] = _history_requirement_for(reading)
    return result


@app.post("/report_incident")
def report_incident(report: IncidentReport, authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    service.reputation.record_flag(report.device_id)
    service.known_sensors.add(report.device_id)
    service._event("incident_reported", None, {
        "device_id": report.device_id,
        "incident_type": report.incident_type,
        "evidence_fields": sorted(report.evidence.keys()),
    })
    return {"status": "recorded", "device_id": report.device_id}


def _apply_twin_containment(tool: str, *, device_ids: list[str], reading_ids: list[str] | None = None,
                            reason: str | None = None, caused_by: list[str] | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {"device_ids": device_ids, "caused_by": caused_by or []}
    if tool in {"isolate_sensor", "quarantine_device"}:
        args["reason"] = reason
    if tool == "rollback_reading":
        args = {"reading_ids": reading_ids or [], "caused_by": caused_by or []}
    try:
        twin_result = call_twin_tool_sync(tool, args)
    except TwinToolRejected as exc:
        _audit_log.record(run_id=_latest_twin_run_id or "untracked", event_type="containment_effect",
            reading_id=(reading_ids or [None])[0], trust_score=None, verdict=None, action=tool,
            decision="rejected", reason=exc.code or "twin_tool_rejected", caused_by=(caused_by or [None])[0],
            data={"device_ids": device_ids, "reading_ids": list(reading_ids or []),
                  "error": exc.message})
        if exc.code in {"CAP_EXCEEDED", "INVALID_CAUSED_BY", "INVALID_DEVICE_IDS",
                        "INVALID_REASON", "INVALID_READING_IDS", "NO_TRUSTED_VALUE",
                        "READING_NOT_PUBLISHED", "UNKNOWN_DEVICE", "UNKNOWN_READING"}:
            raise HTTPException(status_code=409,
                detail={"code": exc.code, "message": exc.message}) from exc
        raise HTTPException(status_code=503, detail="twin_containment_unavailable") from exc
    except TwinDiscoveryError as exc:
        _audit_log.record(run_id=_latest_twin_run_id or "untracked", event_type="containment_effect",
            reading_id=(reading_ids or [None])[0], trust_score=None, verdict=None, action=tool,
            decision="failed", reason="twin_containment_unavailable", caused_by=(caused_by or [None])[0],
            data={"device_ids": device_ids, "reading_ids": list(reading_ids or []),
                  "error": str(exc)[:240]})
        raise HTTPException(status_code=503, detail="twin_containment_unavailable") from exc
    if not isinstance(twin_result, dict):
        raise HTTPException(status_code=502, detail="twin_containment_unconfirmed")

    if tool in {"isolate_sensor", "quarantine_device", "rollback_reading"}:
        if twin_result.get("status") == "rejected":
            raise HTTPException(status_code=409, detail={"code": twin_result.get("code"), "twin": twin_result})
        confirmed = (twin_result.get("status") == "applied"
                     and isinstance(twin_result.get("run_id"), str) and bool(twin_result.get("run_id")))
    else:
        confirmed = (isinstance(twin_result.get("released"), list)
                     and isinstance(twin_result.get("not_contained"), list)
                     and isinstance(twin_result.get("run_id"), str))
    if not confirmed:
        raise HTTPException(status_code=502, detail="twin_containment_unconfirmed")

    # Twin's confirmed result is authoritative; this local state only mirrors
    # the effect so Guardian's own scoring can see the containment.
    if tool == "isolate_sensor":
        for device_id in device_ids:
            service.reputation.set_isolated(device_id, True)
            service.known_sensors.add(device_id)
    elif tool == "quarantine_device":
        for device_id in device_ids:
            service.reputation.set_quarantined(device_id, True)
            service.known_sensors.add(device_id)
    elif tool == "release_device":
        for device_id in device_ids:
            service.reputation.set_isolated(device_id, False)
            service.reputation.set_quarantined(device_id, False)
    else:
        for reading_id in (reading_ids or []):
            service.invalidate_reading(reading_id, caused_by=caused_by)

    run_id = twin_result.get("run_id") or _latest_twin_run_id or "untracked"
    corrections = twin_result.get("corrections", [])
    affected_devices = list(device_ids)
    if tool == "rollback_reading" and isinstance(corrections, list):
        affected_devices = sorted({item.get("device_id") for item in corrections
                                   if isinstance(item, dict) and isinstance(item.get("device_id"), str)})
    identity = json.dumps({"run_id": run_id, "tool": tool,
                           "device_ids": sorted(affected_devices),
                           "reading_ids": sorted(reading_ids or []),
                           "caused_by": sorted(caused_by or [])}, sort_keys=True, separators=(",", ":"))
    event = {
        "schema_version": "guardian.containment.v1",
        "event_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "run_id": run_id,
        "tool": tool,
        "status": "applied",
        "device_ids": affected_devices,
        "reading_ids": list(reading_ids or []),
        "reason": reason,
        "caused_by": list(caused_by or []),
        "twin_result": twin_result,
        "occurred_at": time.time(),
    }
    try:
        brain_result = notify_containment_mcp_sync(event)
        if isinstance(brain_result, dict) and (brain_result.get("status") in {"rejected", "error"}
                                                or brain_result.get("accepted") is False):
            notification = {"status": "failed", "result": brain_result}
        else:
            notification = {"status": "notified", "result": brain_result}
    except BrainDeliveryError as exc:
        notification = {"status": "failed", "reason": str(exc)}

    service._event("containment_effect", None, {
        "tool": tool, "device_ids": affected_devices, "reading_ids": list(reading_ids or []),
        "twin_status": twin_result.get("status", "applied"),
        "brain_notification": notification["status"],
    })
    _audit_log.record(run_id=run_id, event_type="containment_effect",
        reading_id=(reading_ids or [None])[0], trust_score=None, verdict=None, action=tool,
        decision="applied", reason=None if notification["status"] == "notified" else "brain_notification_failed",
        caused_by=(caused_by or (reading_ids or [None]))[0],
        data={"device_ids": affected_devices, "reading_ids": list(reading_ids or []),
              "brain_notification": notification["status"]})
    return {"status": "applied", "tool": tool, "twin": twin_result,
            "brain_notification": notification}


@app.post("/quarantine_device/{device_id}")
def quarantine_device(device_id: str, request: ContainmentMetadata | None = Body(default=None),
                      authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    metadata = request or ContainmentMetadata()
    return _apply_twin_containment("quarantine_device", device_ids=[device_id],
                                   reason=metadata.reason, caused_by=metadata.caused_by)


@app.post("/isolate_sensor/{sensor_id}")
def isolate_sensor(sensor_id: str, request: ContainmentMetadata | None = Body(default=None),
                   authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    metadata = request or ContainmentMetadata()
    return _apply_twin_containment("isolate_sensor", device_ids=[sensor_id],
                                   reason=metadata.reason, caused_by=metadata.caused_by)


@app.post("/release_device/{device_id}")
def release_device(device_id: str, request: ContainmentMetadata | None = Body(default=None),
                   authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    metadata = request or ContainmentMetadata()
    return _apply_twin_containment("release_device", device_ids=[device_id],
                                   caused_by=metadata.caused_by)


@app.post("/rollback_reading")
def rollback_reading(request: RollbackRequest, authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    reading_ids = request.reading_ids or ([request.reading_id] if request.reading_id else [])
    if request.sensor_id:
        for reading_id in reading_ids:
            reading = service.buffer.get_reading(reading_id)
            if reading is not None:
                original = next((item.get("original_reading", {}) for item in reversed(service.evaluations)
                                 if item.get("reading_id") == reading_id), {})
                if original.get("device_id", reading.sensor_id) != request.sensor_id:
                    raise HTTPException(status_code=404, detail="reading_not_found")
    return _apply_twin_containment("rollback_reading", device_ids=[], reading_ids=reading_ids,
                                   caused_by=request.caused_by)


@app.get("/reputation/{sensor_id}")
def get_reputation(sensor_id: str):
    rep = service.reputation.get(sensor_id)
    return {
        "sensor_id": rep.sensor_id,
        "decayed_flag_score": service.reputation.recent_flags(sensor_id),
        "raw_flag_count": len(rep.flags),
        "quarantined": rep.quarantined,
        "isolated": rep.isolated,
    }


@app.get("/api/{unknown_path:path}")
def unknown_api_path(unknown_path: str):
    raise HTTPException(status_code=404, detail="api_endpoint_not_found")


# Keep the existing model inspector, MCP endpoint, and built React assets in
# this one process. This fallback is deliberately registered after API routes.
app.mount(
    "/",
    mcp_app,
    name="model-inspector-and-mcp",
)
