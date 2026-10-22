"""
Guardian Layer service.

Exposes:
  POST /ingest                     -- Twin pushes a new sensor reading here
  GET  /trust_verdict/{sid}/{rid}  -- City Brain calls this before acting
  POST /report_incident            -- log an incident for audit
  POST /quarantine_device/{id}     -- containment action
  POST /isolate_sensor/{id}        -- containment action
  POST /rollback_reading           -- containment action
  GET  /reputation/{sensor_id}     -- debug/inspection endpoint
  GET  /health                     -- liveness check

Run with:
  uvicorn guardian.main:app --reload --port 8001
"""

import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from .models import SensorReading, TrustVerdict
from .buffer import SensorBuffer
from .reputation import ReputationStore
from .scoring import compute_trust_score
from .security import verify_signature

app = FastAPI(title="Guardian Layer", version="0.1.0")

# In-memory state -- fine for a hackathon demo. Swap for Redis/Postgres
# if you need persistence across restarts or multiple worker processes.
buffer = SensorBuffer()
reputation = ReputationStore()
verdict_log: dict[str, TrustVerdict] = {}  # reading_id -> last verdict


class IngestRequest(BaseModel):
    sensor_id: str
    sensor_type: str
    value: float
    unit: str
    timestamp: float
    location: dict[str, float]
    sequence_number: int
    signature: Optional[str] = None
    incident_type: Optional[str] = None  # set if this reading claims to signal an incident
    require_signature: bool = False      # set True once your Twin actually signs


class IncidentReport(BaseModel):
    device_id: str
    incident_type: str
    evidence: dict


class RollbackRequest(BaseModel):
    sensor_id: str
    reading_id: str


@app.get("/health")
def health():
    return {"status": "ok", "time": time.time()}


@app.post("/ingest")
def ingest(req: IngestRequest):
    # --- Layer A: protocol checks ---
    if buffer.is_replay_or_out_of_order(req.sensor_id, req.sequence_number):
        raise HTTPException(
            status_code=409,
            detail="replay_or_out_of_order_sequence_number",
        )

    if req.require_signature:
        if not req.signature or not verify_signature(
            req.sensor_id, req.sensor_type, req.value,
            req.timestamp, req.sequence_number, req.signature,
        ):
            raise HTTPException(status_code=401, detail="invalid_signature")

    if reputation.is_contained(req.sensor_id):
        # A quarantined/isolated sensor's new readings are accepted for
        # audit purposes but immediately marked compromised.
        pass

    reading = SensorReading(
        sensor_id=req.sensor_id,
        sensor_type=req.sensor_type,  # type: ignore[arg-type]
        value=req.value,
        unit=req.unit,
        timestamp=req.timestamp,
        location=req.location,
        sequence_number=req.sequence_number,
        signature=req.signature,
    )
    buffer.add(reading)

    if reputation.is_contained(req.sensor_id):
        verdict = TrustVerdict(
            sensor_id=reading.sensor_id,
            reading_id=reading.reading_id,
            trust_score=0.0,
            verdict="compromised",
            reasons=["sensor_currently_contained"],
        )
    else:
        verdict = compute_trust_score(
            reading, buffer, reputation, incident_type=req.incident_type
        )

    verdict_log[reading.reading_id] = verdict
    return {"reading_id": reading.reading_id, "verdict": verdict.to_dict()}


@app.get("/trust_verdict/{sensor_id}/{reading_id}")
def get_trust_verdict(sensor_id: str, reading_id: str):
    verdict = verdict_log.get(reading_id)
    if not verdict or verdict.sensor_id != sensor_id:
        raise HTTPException(status_code=404, detail="verdict_not_found")
    return verdict.to_dict()


@app.post("/report_incident")
def report_incident(report: IncidentReport):
    reputation.record_flag(report.device_id)
    return {"status": "recorded", "device_id": report.device_id}


@app.post("/quarantine_device/{device_id}")
def quarantine_device(device_id: str):
    reputation.set_quarantined(device_id, True)
    return {"status": "quarantined", "device_id": device_id, "timestamp": time.time()}


@app.post("/isolate_sensor/{sensor_id}")
def isolate_sensor(sensor_id: str):
    reputation.set_isolated(sensor_id, True)
    return {"status": "isolated", "sensor_id": sensor_id, "timestamp": time.time()}


@app.post("/rollback_reading")
def rollback_reading(req: RollbackRequest):
    reading = buffer.get_reading(req.reading_id)
    if not reading or reading.sensor_id != req.sensor_id:
        raise HTTPException(status_code=404, detail="reading_not_found")

    # Look at history BEFORE marking this reading invalid, so we can still
    # find it if needed -- but history() already excludes any OTHER
    # previously-invalidated readings, so "prior" is always the last
    # genuinely-trusted value, never another rolled-back fake.
    history = buffer.history(req.sensor_id)
    prior = [r for r in history if r.sequence_number < reading.sequence_number]
    restored = prior[-1].value if prior else None

    # Actually invalidate it: from now on, rate-of-change checks, z-score
    # baselines, and correlation evidence all skip this reading. Without
    # this line, a rolled-back spoof was still silently poisoning future
    # comparisons -- which is exactly the bug we hit with test_01 earlier.
    buffer.mark_invalid(req.reading_id)

    return {
        "status": "rolled_back",
        "sensor_id": req.sensor_id,
        "reading_id": req.reading_id,
        "restored_value": restored,
        "invalidated": True,
    }


@app.get("/reputation/{sensor_id}")
def get_reputation(sensor_id: str):
    rep = reputation.get(sensor_id)
    return {
        "sensor_id": rep.sensor_id,
        "decayed_flag_score": reputation.recent_flags(sensor_id),
        "raw_flag_count": len(rep.flags),
        "quarantined": rep.quarantined,
        "isolated": rep.isolated,
    }