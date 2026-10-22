"""
Shared data models for the Guardian Layer.

These mirror the schema you should agree on with your Twin and City Brain
teammates BEFORE writing detection logic. If their message shape differs,
change it here first -- everything else in this package depends on these
shapes.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal, Any
import time
import uuid


SensorType = Literal[
    "traffic_cam",
    "water_level",
    "power_load",
    "air_quality",
    "emergency_call",
]

IncidentType = Literal["fire", "flood", "accident", "traffic_jam", "cyberattack"]

Verdict = Literal["trusted", "suspect", "compromised"]


@dataclass
class SensorReading:
    sensor_id: str
    sensor_type: SensorType
    value: float
    unit: str
    timestamp: float                 # unix epoch seconds
    location: dict[str, float]       # {"lat": ..., "lng": ...}
    sequence_number: int             # strictly increasing per sensor_id
    signature: Optional[str] = None  # HMAC hex digest, see security.py
    reading_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class ActuatorCommand:
    actuator_id: str
    actuator_type: str
    command: str
    issued_by: str                   # "city_brain" | "guardian"
    timestamp: float
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class TrustVerdict:
    sensor_id: str
    reading_id: str
    trust_score: float                # 0.0 - 1.0
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "reading_id": self.reading_id,
            "trust_score": round(self.trust_score, 3),
            "verdict": self.verdict,
            "reasons": self.reasons,
            "timestamp": self.timestamp,
        }
