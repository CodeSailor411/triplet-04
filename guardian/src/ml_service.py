"""Adapter from Guardian Layer history to the saved RF model's exact contract.

Feature definitions follow ``models/generate_dataset_v2.py``. Values are only
converted where the source and model units have an explicit equivalence.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

from app import DECISION_THRESHOLD, METADATA, SENSOR_CONFIG, UNCERTAINTY_BAND, load_model, predict_reading


SENSOR_DOMAIN = {
    "traffic_cam": "traffic",
    "water_level": "water",
    "power_load": "power",
    "air_quality": "air_quality",
    "emergency_call": "emergency",
}


@dataclass
class AdvisoryEvaluation:
    status: str
    model_available: bool
    probability: float | None = None
    label: str = "Unavailable"
    threshold: float = DECISION_THRESHOLD
    uncertainty_band: float = UNCERTAINTY_BAND
    signals: list[str] | None = None
    features: dict[str, Any] | None = None
    error: str | None = None
    model_version: str = str(METADATA.get("model_version", "unknown"))
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model_available": self.model_available,
            "probability": self.probability,
            "label": self.label,
            "threshold": self.threshold,
            "uncertainty_band": self.uncertainty_band,
            "signals": self.signals or [],
            "features": self.features,
            "error": self.error,
            "model_version": self.model_version,
            "advisory_only": self.advisory_only,
        }


def model_value(sensor_type: str, value: float, unit: str) -> tuple[str, float] | None:
    """Return the model domain/value only for known unit mappings."""
    domain = SENSOR_DOMAIN.get(sensor_type)
    if domain is None:
        return None
    if sensor_type == "water_level":
        if unit in {"cm", "centimeter", "centimeters"}:
            return domain, value
        if unit in {"m", "meter", "meters"}:
            return domain, value * 100.0
        return None
    accepted_units = {
        "traffic_cam": {"percent", "%"},
        "power_load": {"kW"},
        # AQI has no lossless conversion to the model's PM2.5 feature.
        "air_quality": {"ug/m3", "µg/m³"},
        "emergency_call": {"calls_per_min", "calls/min"},
    }[sensor_type]
    if unit not in accepted_units:
        return None
    return domain, value


def layer_value(sensor_type: str, value: float, unit: str) -> tuple[float, str]:
    """Normalize explicit aliases and water cm to the Layer's existing metres."""
    if sensor_type == "water_level":
        if unit in {"cm", "centimeter", "centimeters"}:
            return value / 100.0, "m"
        if unit in {"m", "meter", "meters"}:
            return value, "m"
    aliases = {
        "traffic_cam": {"%": "percent"},
        "emergency_call": {"calls/min": "calls_per_min"},
        "air_quality": {"µg/m³": "ug/m3"},
    }
    return value, aliases.get(sensor_type, {}).get(unit, unit)


def _history_model_values(sensor_type: str, history: list[Any]) -> list[float] | None:
    values: list[float] = []
    for reading in history:
        mapped = model_value(sensor_type, float(reading.value), reading.unit)
        if mapped is None:
            return None
        values.append(mapped[1])
    return values


def build_model_features(
    *,
    sensor_type: str,
    value: float,
    unit: str,
    history: list[Any],
    correlation_strength: float,
    incident_claimed: bool,
    decayed_flags: float,
) -> tuple[dict[str, Any] | None, str | None]:
    """Derive the generator's ten raw model fields from actual accepted history."""
    mapped = model_value(sensor_type, value, unit)
    if mapped is None:
        if sensor_type == "air_quality" and unit == "AQI":
            return None, "unsupported_quantity:AQI cannot be converted to PM2.5"
        return None, f"unsupported_unit:{unit} for {sensor_type}"
    if not history:
        return None, "insufficient_history:need a prior reading for rate and baseline features"

    domain, model_reading_value = mapped
    past = _history_model_values(sensor_type, history[-30:])
    if past is None:
        return None, "incompatible_history_units:prior readings do not share the model quantity"
    config = SENSOR_CONFIG["domains"][domain]
    span = float(config["hi"] - config["lo"])
    window = past[-6:]
    if len(window) >= 3:
        sigma = max(statistics.pstdev(window), 0.005 * span)
        z_score = (model_reading_value - statistics.mean(window)) / sigma
    else:
        z_score = 0.0
    baseline = statistics.median(past)
    rate_of_change = abs(model_reading_value - past[-1])
    flat_run_len = 0
    for previous in reversed(past):
        if abs(previous - model_reading_value) < 1e-9:
            flat_run_len += 1
        else:
            break
    features = {
        "domain": domain,
        "value": model_reading_value,
        "z_score": z_score,
        # The model was trained on change per simulation tick. Guardian's B
        # rate check independently uses change per elapsed second.
        "rate_of_change": rate_of_change,
        "out_of_bounds": int(not (config["lo"] <= model_reading_value <= config["hi"])),
        "correlation_strength": correlation_strength,
        "incident_claimed": int(incident_claimed),
        "decayed_flags": decayed_flags,
        "baseline_dev_norm": (model_reading_value - baseline) / span,
        "flat_run_len": flat_run_len,
    }
    return features, None


def evaluate_advisory(
    *,
    sensor_type: str,
    value: float,
    unit: str,
    history: list[Any],
    correlation_strength: float,
    incident_claimed: bool,
    decayed_flags: float,
    force_unavailable: bool = False,
) -> AdvisoryEvaluation:
    if force_unavailable:
        return AdvisoryEvaluation(
            status="unavailable",
            model_available=False,
            error="injected_model_unavailable: inference disabled for this simulation scenario",
        )
    features, unavailable_reason = build_model_features(
        sensor_type=sensor_type,
        value=value,
        unit=unit,
        history=history,
        correlation_strength=correlation_strength,
        incident_claimed=incident_claimed,
        decayed_flags=decayed_flags,
    )
    if features is None:
        return AdvisoryEvaluation(
            status="unavailable",
            model_available=load_model() is not None,
            error=unavailable_reason,
        )
    try:
        result = predict_reading(features)
    except Exception as exc:  # inference failure is data, never a trusted fallback
        return AdvisoryEvaluation(
            status="error",
            model_available=load_model() is not None,
            features=features,
            error=f"{type(exc).__name__}: {exc}",
        )
    if result.ml_probabilities is None:
        return AdvisoryEvaluation(
            status="unavailable",
            model_available=result.model_available,
            label=result.ml_label,
            threshold=result.decision_threshold,
            signals=result.signals,
            features=features,
            error="model_unavailable_or_abstained",
            model_version=result.model_version,
        )
    probability = float(result.ml_probabilities.suspicious)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        return AdvisoryEvaluation(
            status="error",
            model_available=True,
            features=features,
            error="model_returned_invalid_probability",
            model_version=result.model_version,
        )
    return AdvisoryEvaluation(
        status="available",
        model_available=True,
        probability=probability,
        label=result.ml_label,
        threshold=result.decision_threshold,
        signals=result.signals,
        features=features,
        model_version=result.model_version,
    )
