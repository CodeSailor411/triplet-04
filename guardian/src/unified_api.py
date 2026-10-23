"""Single FastAPI entry point for the Guardian + RF + City Brain mock."""
from __future__ import annotations

import time
import hmac
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Body, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, model_validator
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
from token_service import ActionTokenService, TokenError
from twin_adapter import normalize_twin_reading


SensorType = Literal["traffic_cam", "water_level", "power_load", "air_quality", "emergency_call"]
IncidentType = Literal["fire", "flood", "accident", "traffic_jam", "cyberattack"]
ALLOWED_UNITS = {
    "traffic_cam": {"percent", "%"},
    "water_level": {"cm", "centimeter", "centimeters", "m", "meter", "meters"},
    "power_load": {"kW"},
    "air_quality": {"AQI", "ug/m3", "µg/m³"},
    "emergency_call": {"calls_per_min", "calls/min"},
}


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor_id: str = Field(min_length=1, max_length=128)
    sensor_type: SensorType
    value: FiniteFloat
    unit: str = Field(min_length=1, max_length=32)
    timestamp: FiniteFloat = Field(gt=0)
    location: dict[str, FiniteFloat]
    sequence_number: StrictInt = Field(ge=0)
    signature: str | None = Field(default=None, max_length=256)
    incident_type: IncidentType | None = None
    require_signature: StrictBool = False
    reading_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_unit_and_location(self):
        if self.unit not in ALLOWED_UNITS[self.sensor_type]:
            raise ValueError(f"unit {self.unit!r} is not supported for {self.sensor_type}")
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
    sensor_id: str = Field(min_length=1, max_length=128)
    reading_id: str = Field(min_length=1, max_length=128)


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
    risk_level: Literal["R1", "R2", "R3", "NONE"]
    domain: str | None = None


class TokenVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=8192)
    action: str = Field(min_length=1, max_length=128)
    parameters: dict


class RollbackPoolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    reading_id: str = Field(min_length=1, max_length=128)


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

_action_policy = ActionPolicy()
_audit_log = JsonlAuditLog()
_token_service = ActionTokenService.from_env()


def _require_integration_key(authorization: str | None) -> None:
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
    return describe_capabilities().model_dump(mode="json")


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
def reset_demo():
    service.reset()
    return {"status": "reset", "overview": service.overview()}


@app.post("/api/simulations/{scenario_id}")
def simulate(scenario_id: str, request: SimulationRequest | None = Body(default=None)):
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
def ingest(request: IngestRequest):
    result = service.process_reading(request.model_dump())
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
    results = []
    skipped = []
    for item in readings:
        try:
            if not isinstance(item, dict) or item.get("run_id") != run_id:
                raise ValueError("reading run_id must match its event envelope")
            payload = normalize_twin_reading(item)
            evaluation = service.process_reading(payload)
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
    return {"run_id": run_id, "processed": len(results), "skipped": skipped, "results": results}


@app.post("/api/actions/authorize")
def authorize_action(request: ActionAuthorizationRequest, authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    verdict = service.verdict_log.get(request.reading_id)
    if verdict is None:
        _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
            trust_score=None, verdict=None, action=request.action, decision="denied",
            reason="verdict_not_found", caused_by=request.reading_id)
        raise HTTPException(status_code=404, detail="verdict_not_found")
    evaluated = next((e for e in reversed(service.evaluations) if e["reading_id"] == request.reading_id), None)
    sensor_domain = {
        "traffic_cam": "Traffic", "water_level": "Water", "power_load": "Power",
        "air_quality": "Air Quality", "emergency_call": "Emergency",
    }.get(evaluated["sensor_type"] if evaluated else "")
    if sensor_domain is None or (request.domain or "").casefold() != sensor_domain.casefold():
        try:
            denied_action = _action_policy.normalize(request.action)
        except ActionPolicyError:
            denied_action = request.action
        _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
            trust_score=verdict.trust_score, verdict=verdict.verdict, action=denied_action,
            decision="denied", reason="reading_domain_mismatch_or_unsupported_domain",
            caused_by=request.reading_id)
        raise HTTPException(status_code=403, detail="reading_domain_mismatch_or_unsupported_domain")
    normalized = request.action
    try:
        if _token_service.private_key is None:
            raise TokenError("signing_key_unavailable")
        normalized = _action_policy.normalize(request.action)
        normalized, _ = _action_policy.authorize(run_id=request.run_id, action=request.action,
            parameters=request.parameters, trust_score=verdict.trust_score,
            risk_level=request.risk_level, domain=request.domain)
        token, claims = _token_service.issue(run_id=request.run_id, action=normalized,
            parameters=request.parameters, reading_id=request.reading_id,
            trust_score=verdict.trust_score, risk_level=request.risk_level)
    except ActionPolicyError as exc:
        reason = str(exc)
        _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
            trust_score=verdict.trust_score, verdict=verdict.verdict, action=normalized,
            decision="denied", reason=reason, caused_by=request.reading_id)
        raise HTTPException(status_code=403, detail=reason) from exc
    except TokenError as exc:
        reason = str(exc)
        _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
            trust_score=verdict.trust_score, verdict=verdict.verdict, action=normalized,
            decision="denied", reason=reason, caused_by=request.reading_id)
        raise HTTPException(status_code=503, detail=reason) from exc
    _audit_log.record(run_id=request.run_id, event_type="action_decision", reading_id=request.reading_id,
        trust_score=verdict.trust_score, verdict=verdict.verdict, action=normalized,
        decision="approved", reason=None, caused_by=request.reading_id,
        data={"token_id": claims["token_id"]})
    return {"decision": "approved", "reading_id": request.reading_id,
            "action": normalized, "token": token, "token_id": claims["token_id"], "expires_at": claims["exp"]}


@app.post("/api/actions/verify")
def verify_action_token(request: TokenVerifyRequest, authorization: str | None = Header(default=None)):
    _require_integration_key(authorization)
    try:
        normalized = _action_policy.normalize(request.action)
        claims = _token_service.verify(request.token, action=normalized, parameters=request.parameters)
    except (TokenError, ActionPolicyError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"verified": True, "token_id": claims["token_id"], "run_id": claims["run_id"],
            "reading_id": claims["reading_id"], "expires_at": claims["exp"]}


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
    verdict = service.verdict_log.get(reading_id)
    if not verdict or verdict.sensor_id != sensor_id:
        raise HTTPException(status_code=404, detail="verdict_not_found")
    return verdict.to_dict()


@app.post("/report_incident")
def report_incident(report: IncidentReport):
    service.reputation.record_flag(report.device_id)
    service.known_sensors.add(report.device_id)
    service._event("incident_reported", None, {
        "device_id": report.device_id,
        "incident_type": report.incident_type,
        "evidence_fields": sorted(report.evidence.keys()),
    })
    return {"status": "recorded", "device_id": report.device_id}


@app.post("/quarantine_device/{device_id}")
def quarantine_device(device_id: str):
    service.reputation.set_quarantined(device_id, True)
    service.known_sensors.add(device_id)
    return {"status": "quarantined", "device_id": device_id, "timestamp": time.time(), "simulated": True}


@app.post("/isolate_sensor/{sensor_id}")
def isolate_sensor(sensor_id: str):
    service.reputation.set_isolated(sensor_id, True)
    service.known_sensors.add(sensor_id)
    return {"status": "isolated", "sensor_id": sensor_id, "timestamp": time.time(), "simulated": True}


@app.post("/rollback_reading")
def rollback_reading(request: RollbackRequest):
    reading = service.buffer.get_reading(request.reading_id)
    if not reading or reading.sensor_id != request.sensor_id:
        raise HTTPException(status_code=404, detail="reading_not_found")
    history = service.buffer.history(request.sensor_id)
    prior = [r for r in history if r.sequence_number < reading.sequence_number]
    restored = prior[-1].value if prior else None
    service.buffer.mark_invalid(request.reading_id)
    service._event("reading_rolled_back", request.reading_id, {
        "sensor_id": request.sensor_id,
        "restored_value": restored,
    })
    return {
        "status": "rolled_back",
        "sensor_id": request.sensor_id,
        "reading_id": request.reading_id,
        "restored_value": restored,
        "invalidated": True,
    }


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
