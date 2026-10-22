"""Deterministic synthetic scenarios routed through the live integration service."""
from __future__ import annotations

import time
import uuid
from typing import Any

from integration_service import GuardianIntegration


SCENARIOS = [
    {"id": "normal", "name": "Normal operation", "description": "Baseline readings followed by a nominal sensor update."},
    {"id": "genuine_fire", "name": "Genuine fire emergency", "description": "Fire evidence arrives with rising PM2.5 and emergency calls."},
    {"id": "fake_fire", "name": "Fake fire alert", "description": "An isolated fire claim has no air-quality or emergency corroboration."},
    {"id": "replay", "name": "Replay attack", "description": "The same sequence number is submitted twice to Layer A."},
    {"id": "invalid_signature", "name": "Invalid signature", "description": "A required HMAC check receives a forged signature."},
    {"id": "physical_anomaly", "name": "Physical anomaly", "description": "The reading exceeds configured physical bounds and rate limits."},
    {"id": "stuck_sensor", "name": "Stuck sensor", "description": "Repeated identical values exercise the deterministic flatline health gate."},
    {"id": "adaptive_ramp", "name": "Adaptive ramp", "description": "A gradual in-range change arrives with forged corroborating signals."},
    {"id": "model_unavailable", "name": "Model unavailable", "description": "Inference is deliberately unavailable for the focus reading; Guardian rules still run."},
    {"id": "corroborated_spoof", "name": "Corroborated spoofing", "description": "A forged fire story matches the evidence expected by correlation checks."},
    {"id": "custom", "name": "Custom sensor reading", "description": "Warm a selected sensor with baseline data, then evaluate your value."},
]

SENSORS = [
    {"sensor_type": "traffic_cam", "domain": "traffic", "unit": "percent", "default_value": 45.0},
    {"sensor_type": "water_level", "domain": "water", "unit": "cm", "default_value": 62.0},
    {"sensor_type": "power_load", "domain": "power", "unit": "kW", "default_value": 500.0},
    {"sensor_type": "air_quality", "domain": "air_quality", "unit": "ug/m3", "default_value": 18.0},
    {"sensor_type": "emergency_call", "domain": "emergency", "unit": "calls_per_min", "default_value": 1.0},
]


def scenario_catalog() -> dict[str, Any]:
    return {"scenarios": SCENARIOS, "sensors": SENSORS, "synthetic": True}


def _run_id() -> str:
    return uuid.uuid4().hex[:10]


def run_scenario(
    service: GuardianIntegration,
    scenario_id: str,
    *,
    sensor_type: str | None = None,
    value: float | None = None,
) -> dict[str, Any]:
    if scenario_id not in {scenario["id"] for scenario in SCENARIOS}:
        raise ValueError(f"Unknown scenario {scenario_id!r}")
    if scenario_id == "custom" and sensor_type is None:
        raise ValueError("Custom scenario requires sensor_type")
    run_id = _run_id()
    started = time.time()
    base = started + 1.0
    location = {"lat": 37.27, "lng": 9.87}
    evaluations: list[dict[str, Any]] = []
    target_ids: list[str] = []

    def emit(
        name: str,
        kind: str,
        unit: str,
        reading_value: float,
        seq: int,
        ts: float,
        *,
        incident_type: str | None = None,
        require_signature: bool = False,
        signature: str | None = None,
        focus: bool = False,
        force_unavailable: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "sensor_id": f"{run_id}-{name}",
            "sensor_type": kind,
            "value": float(reading_value),
            "unit": unit,
            "timestamp": ts,
            "location": location,
            "sequence_number": seq,
            "incident_type": incident_type,
            "require_signature": require_signature,
            "signature": signature,
        }
        result = service.process_reading(
            payload,
            synthetic=True,
            force_model_unavailable=force_unavailable,
        )
        result["simulation_focus"] = focus
        evaluations.append(result)
        if focus:
            target_ids.append(result["reading_id"])
        return result

    def baseline(name: str, kind: str, unit: str, start: float, count: int = 6) -> tuple[str, float]:
        sensor_id = f"{run_id}-{name}"
        for index in range(count):
            emit(name, kind, unit, start + index * (0.05 if kind != "water_level" else 0.1), index + 1, base + index * 5)
        return sensor_id, base + (count - 1) * 5

    if scenario_id == "normal":
        baseline("water-normal", "water_level", "cm", 60.0)
        emit("water-normal", "water_level", "cm", 62.0 if value is None else value, 7, base + 30, focus=True)

    elif scenario_id in {"genuine_fire", "corroborated_spoof"}:
        # Signals are individually received before the power-load incident claim.
        baseline("air", "air_quality", "ug/m3", 10.0)
        baseline("emergency", "emergency_call", "calls_per_min", 0.3)
        baseline("power", "power_load", "kW", 450.0)
        emit("air", "air_quality", "ug/m3", 24.0, 7, base + 90)
        emit("emergency", "emergency_call", "calls_per_min", 2.0, 7, base + 95)
        emit("power", "power_load", "kW", 500.0, 7, base + 100, incident_type="fire", focus=True)

    elif scenario_id == "fake_fire":
        baseline("power-isolated", "power_load", "kW", 450.0)
        emit("power-isolated", "power_load", "kW", 480.0, 7, base + 30, incident_type="fire", focus=True)

    elif scenario_id == "replay":
        baseline("traffic-replay", "traffic_cam", "percent", 40.0)
        replay_payload = {
            "sensor_id": f"{run_id}-traffic-replay",
            "sensor_type": "traffic_cam",
            "value": 42.0,
            "unit": "percent",
            "timestamp": base + 30,
            "location": location,
            "sequence_number": 7,
        }
        accepted = service.process_reading(replay_payload, synthetic=True)
        accepted["simulation_focus"] = False
        evaluations.append(accepted)
        rejected = service.process_reading(replay_payload, synthetic=True)
        rejected["simulation_focus"] = True
        evaluations.append(rejected)
        target_ids.append(rejected["reading_id"])

    elif scenario_id == "invalid_signature":
        # A fails before the buffer, scorer, or model sees this reading.
        result = emit(
            "signed-power", "power_load", "kW", 500.0, 1, base,
            require_signature=True, signature="0" * 64, focus=True,
        )

    elif scenario_id == "physical_anomaly":
        baseline("power-anomaly", "power_load", "kW", 450.0)
        emit("power-anomaly", "power_load", "kW", 7000.0, 7, base + 30, focus=True)

    elif scenario_id == "stuck_sensor":
        for index in range(6):
            emit("water-stuck", "water_level", "cm", 62.0, index + 1, base + index * 5, focus=index >= 3)
        target_ids.append(evaluations[-1]["reading_id"])

    elif scenario_id == "adaptive_ramp":
        baseline("power-ramp", "power_load", "kW", 450.0)
        baseline("air-ramp", "air_quality", "ug/m3", 10.0)
        baseline("emergency-ramp", "emergency_call", "calls_per_min", 0.3)
        emit("air-ramp", "air_quality", "ug/m3", 24.0, 7, base + 30)
        emit("emergency-ramp", "emergency_call", "calls_per_min", 2.0, 7, base + 35)
        for index in range(1, 7):
            emit(
                "power-ramp", "power_load", "kW", 450.25 + 50.0 * index,
                6 + index, base + (5 + index) * 5,
                incident_type="fire", focus=index == 6,
            )

    elif scenario_id == "model_unavailable":
        baseline("power-no-model", "power_load", "kW", 450.0)
        emit(
            "power-no-model", "power_load", "kW", 455.0, 7, base + 30,
            focus=True, force_unavailable=True,
        )

    elif scenario_id == "custom":
        spec = next((item for item in SENSORS if item["sensor_type"] == sensor_type), None)
        if spec is None:
            raise ValueError(f"Unsupported sensor_type {sensor_type!r}")
        reading_unit = spec["unit"]
        selected_value = spec["default_value"] if value is None else value
        baseline("custom-sensor", sensor_type, reading_unit, selected_value - 1.0)
        emit("custom-sensor", sensor_type, reading_unit, selected_value, 7, base + 30, focus=True)

    focus = next((item for item in reversed(evaluations) if item["reading_id"] in target_ids), evaluations[-1])
    completed = time.time()
    focus["simulation_focus"] = True
    return {
        "scenario_id": scenario_id,
        "run_id": run_id,
        "synthetic": True,
        "started_at": started,
        "completed_at": completed,
        "description": next(item["description"] for item in SCENARIOS if item["id"] == scenario_id),
        "focus_reading_id": focus["reading_id"],
        "evaluations": evaluations,
        "focus_evaluation": focus,
    }
