"""Coordinates the real Guardian Layer checks and advisory model inference."""
from __future__ import annotations

import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_LAYER_ROOT = PROJECT_ROOT / "guardian_layer"
WORKSPACE_LAYER_ROOT = PROJECT_ROOT.parent / "guardian_layer" / "guardian_layer"
LAYER_ROOT = (
    BUNDLED_LAYER_ROOT
    if (BUNDLED_LAYER_ROOT / "guardian").is_dir()
    else WORKSPACE_LAYER_ROOT
)
if str(LAYER_ROOT) not in sys.path:
    sys.path.insert(0, str(LAYER_ROOT))

from guardian.buffer import SensorBuffer  # noqa: E402
from guardian.correlation import CorrelationResult, check_correlation  # noqa: E402
from guardian.models import SensorReading, TrustVerdict  # noqa: E402
from guardian.reputation import ReputationStore  # noqa: E402
from guardian.scoring import compute_trust_score  # noqa: E402
from guardian import validation  # noqa: E402
from guardian.security import verify_signature  # noqa: E402

from ml_service import evaluate_advisory, layer_value  # noqa: E402
from schemas import EvaluationRecord  # noqa: E402
from guardian_policy import load_trust_policy  # noqa: E402


class GuardianIntegration:
    """In-memory state for the loopback mock, shared by API and simulator."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.trust_policy = load_trust_policy()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.RLock()):
            self.buffer = SensorBuffer()
            self.reputation = ReputationStore()
            self.verdict_log: dict[str, TrustVerdict] = {}
            self.evaluations: list[dict[str, Any]] = []
            self.timeline: list[dict[str, Any]] = []
            self.known_sensors: set[str] = set()

    def _event(self, event_type: str, reading_id: str | None, data: dict[str, Any]) -> None:
        self.timeline.append({
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "reading_id": reading_id,
            "occurred_at": time.time(),
            "data": data,
        })

    @staticmethod
    def _public_reading(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "reading_id": payload.get("reading_id"),
            "sensor_id": payload["sensor_id"],
            "sensor_type": payload["sensor_type"],
            "value": payload["value"],
            "unit": payload["unit"],
            "timestamp": payload["timestamp"],
            "sequence_number": payload["sequence_number"],
            "location": payload["location"],
            "incident_type": payload.get("incident_type"),
            "require_signature": payload.get("require_signature", False),
            "signature_present": bool(payload.get("signature")),
        }

    def process_reading(
        self,
        payload: dict[str, Any],
        *,
        synthetic: bool = False,
        force_model_unavailable: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            reading_id = payload.get("reading_id") or str(uuid.uuid4())
            payload = {**payload, "reading_id": reading_id}
            self.known_sensors.add(payload["sensor_id"])
            self._event("reading_received", reading_id, {
                "sensor_id": payload["sensor_id"],
                "sensor_type": payload["sensor_type"],
                "value": payload["value"],
                "unit": payload["unit"],
                "sequence_number": payload["sequence_number"],
                "synthetic": synthetic,
            })
            original = self._public_reading(payload)
            sequence = payload["sequence_number"]
            sid = payload["sensor_id"]
            layer_a = {
                "status": "passed",
                "replay": "passed",
                "signature": "not_required",
                "reason_codes": [],
            }
            reject_reason: str | None = None
            if self.buffer.is_replay_or_out_of_order(sid, sequence):
                reject_reason = "replay_or_out_of_order_sequence_number"
                layer_a["status"] = "failed"
                layer_a["replay"] = "failed"
                layer_a["reason_codes"].append(reject_reason)
            elif payload.get("require_signature"):
                if not payload.get("signature") or not verify_signature(
                    sid,
                    payload["sensor_type"],
                    payload["value"],
                    payload["timestamp"],
                    sequence,
                    payload.get("signature", ""),
                ):
                    reject_reason = "invalid_signature"
                    layer_a["status"] = "failed"
                    layer_a["signature"] = "failed"
                    layer_a["reason_codes"].append(reject_reason)
                else:
                    layer_a["signature"] = "verified"
            elif payload.get("signature"):
                layer_a["signature"] = "present_not_required"

            self._event("layer_a", reading_id, dict(layer_a))
            if reject_reason:
                record = self._rejected_evaluation(
                    reading_id=reading_id,
                    original=original,
                    layer_a=layer_a,
                    reason=reject_reason,
                    synthetic=synthetic,
                )
                self._record(record)
                return record

            layer_reading_value, layer_unit = layer_value(
                payload["sensor_type"], payload["value"], payload["unit"]
            )
            reading = SensorReading(
                sensor_id=sid,
                sensor_type=payload["sensor_type"],
                value=layer_reading_value,
                unit=layer_unit,
                timestamp=payload["timestamp"],
                location=payload["location"],
                sequence_number=sequence,
                signature=payload.get("signature"),
                reading_id=reading_id,
            )
            if self.buffer.get_reading(reading_id):
                # A caller-supplied reading ID must not overwrite an earlier
                # audit record even when its sequence number is newer.
                duplicate = "duplicate_reading_id"
                layer_a["status"] = "failed"
                layer_a["reason_codes"].append(duplicate)
                record = self._rejected_evaluation(
                    reading_id=reading_id,
                    original=original,
                    layer_a=layer_a,
                    reason=duplicate,
                    synthetic=synthetic,
                )
                self._record(record)
                return record

            history_before = self.buffer.history(sid)
            reputation_before = self.reputation.recent_flags(sid)
            raw_flags_before = len(self.reputation.get(sid).flags)
            if self.reputation.is_contained(sid):
                self.buffer.add(reading)
                verdict = TrustVerdict(
                    sensor_id=sid,
                    reading_id=reading_id,
                    trust_score=0.0,
                    verdict="compromised",
                    reasons=["sensor_currently_contained"],
                    timestamp=reading.timestamp,
                )
                record = self._contained_evaluation(
                    reading, original, layer_a, verdict, reputation_before,
                    raw_flags_before, synthetic, payload.get("incident_type"),
                )
                self.verdict_log[reading_id] = verdict
                self._record(record)
                return record

            bounds_failed = validation.violates_bounds(reading)
            rate_failed = validation.violates_rate_of_change(reading, history_before)
            drift_failed = validation.is_statistical_outlier(reading, history_before)
            flat_run = self._flat_run_length(reading, history_before)
            stuck_failed = flat_run >= 3
            layer_b_reasons = []
            if bounds_failed:
                layer_b_reasons.append("out_of_bounds")
            if rate_failed:
                layer_b_reasons.append("rate_of_change_exceeded")
            if drift_failed:
                layer_b_reasons.append("statistical_drift_outlier")
            if stuck_failed:
                layer_b_reasons.append("sensor_stuck")
            layer_b = {
                "status": "failed" if layer_b_reasons else "passed",
                "checks": {
                    "physical_bounds": "failed" if bounds_failed else "passed",
                    "rate_of_change": "failed" if rate_failed else "passed",
                    "statistical_drift": "failed" if drift_failed else "passed",
                    "stuck_sensor": "failed" if stuck_failed else "passed",
                },
                "reason_codes": layer_b_reasons,
                "flat_run_length": flat_run,
            }
            self.buffer.add(reading)
            self._event("layer_b", reading_id, dict(layer_b))

            incident_type = payload.get("incident_type")
            correlation = (
                check_correlation(incident_type, reading.timestamp, self.buffer)
                if incident_type
                else CorrelationResult(expected=False, found=True, strength=1.0, checked=[])
            )
            layer_c = {
                "status": (
                    "not_applicable" if not correlation.expected
                    else "failed" if correlation.strength < 0.34
                    else "uncertain" if correlation.strength < 0.67
                    else "passed"
                ),
                "expected": correlation.expected,
                "found": correlation.found,
                "strength": correlation.strength,
                "checked": correlation.checked,
            }
            self._event("layer_c", reading_id, dict(layer_c))

            ml = evaluate_advisory(
                sensor_type=reading.sensor_type,
                value=payload["value"],
                unit=payload["unit"],
                history=history_before,
                correlation_strength=correlation.strength,
                incident_claimed=bool(incident_type),
                decayed_flags=reputation_before,
                force_unavailable=force_model_unavailable,
            ).to_dict()
            self._event("ml_inference", reading_id, {
                "status": ml["status"],
                "model_available": ml["model_available"],
                "probability": ml["probability"],
                "label": ml["label"],
                "error": ml["error"],
            })

            # The existing scorer owns the score and verdict. ML is attached
            # as explainable advisory evidence with an explicit zero weight.
            verdict = compute_trust_score(
                reading, self.buffer, self.reputation, incident_type=incident_type,
                trusted_threshold=self.trust_policy.trusted_min,
                suspect_threshold=self.trust_policy.suspect_min,
            )
            self.verdict_log[reading_id] = verdict
            raw_flags_after = len(self.reputation.get(sid).flags)
            reputation_after = self.reputation.recent_flags(sid)
            score_reasons = verdict.reasons
            penalty_values = {
                "out_of_bounds": 0.50,
                "rate_of_change_exceeded": 0.35,
                "statistical_drift_outlier": 0.25,
                "no_correlated_evidence": 0.45,
                "weak_correlated_evidence": 0.20,
            }
            breakdown = [
                {"reason_code": code, "penalty": penalty_values[code]}
                for code in score_reasons if code in penalty_values
            ]
            if "prior_flags_on_record" in score_reasons:
                breakdown.append({
                    "reason_code": "prior_flags_on_record",
                    "penalty": min(0.05 * reputation_before, 0.25),
                })
            city_brain = self._city_brain_decision(verdict, layer_a, layer_b, incident_type)
            record = {
                "reading_id": reading_id,
                "sensor_id": sid,
                "timestamp": reading.timestamp,
                "sequence_number": sequence,
                "domain": self._domain(reading.sensor_type),
                "sensor_type": reading.sensor_type,
                "original_reading": original,
                "synthetic": synthetic,
                "incident_type": incident_type,
                "layer_a": layer_a,
                "layer_b": layer_b,
                "layer_c": layer_c,
                "ml": ml,
                "guardian": {
                    **verdict.to_dict(),
                    "scoring_breakdown": {
                        "starting_score": 1.0,
                        "penalties": breakdown,
                        "final_score": verdict.trust_score,
                        "ml_numeric_contribution": 0.0,
                        "ml_treatment": "advisory_only_no_score_weight",
                    },
                },
                "reputation_change": {
                    "decayed_flags_before": reputation_before,
                    "decayed_flags_after": reputation_after,
                    "raw_flags_before": raw_flags_before,
                    "raw_flags_after": raw_flags_after,
                },
                "city_brain": city_brain,
                "action_blocked": not city_brain["allowed"],
            }
            self._event("guardian_verdict", reading_id, {
                "trust_score": verdict.trust_score,
                "verdict": verdict.verdict,
                "reason_codes": verdict.reasons,
                "ml_probability": ml["probability"],
                "ml_numeric_contribution": 0.0,
            })
            if verdict.verdict != "trusted" or stuck_failed or bounds_failed or rate_failed:
                self._event("guardian_alert", reading_id, {
                    "severity": "high" if verdict.verdict == "compromised" or bounds_failed or rate_failed else "warning",
                    "reason_codes": list(dict.fromkeys([*score_reasons, *layer_b_reasons])),
                })
            self._event("city_brain_decision", reading_id, dict(city_brain))
            self._record(record)
            return record

    @staticmethod
    def _domain(sensor_type: str) -> str | None:
        from ml_service import SENSOR_DOMAIN
        return SENSOR_DOMAIN.get(sensor_type)

    @staticmethod
    def _flat_run_length(reading: SensorReading, history: list[SensorReading]) -> int:
        run = 0
        for previous in reversed(history):
            if previous.unit == reading.unit and abs(previous.value - reading.value) < 1e-9:
                run += 1
            else:
                break
        return run

    def _city_brain_decision(
        self,
        verdict: TrustVerdict,
        layer_a: dict[str, Any],
        layer_b: dict[str, Any],
        incident_type: str | None,
    ) -> dict[str, Any]:
        block_reason = None
        checks = layer_b.get("checks", {})
        hard_validation_failure = any(
            checks.get(name) == "failed"
            for name in ("physical_bounds", "rate_of_change", "stuck_sensor")
        )
        if layer_a["status"] != "passed":
            block_reason = "security_failure"
        elif verdict.reasons == ["sensor_currently_contained"]:
            block_reason = "sensor_contained"
        elif hard_validation_failure:
            block_reason = "layer_b_hard_validation_failed"
        elif verdict.verdict != "trusted":
            block_reason = "insufficient_guardian_trust"
        allowed = block_reason is None
        action = (
            "simulated_dispatch" if allowed and incident_type
            else "consume_reading" if allowed
            else "blocked"
        )
        return {
            "status": "allowed" if allowed else "blocked",
            "allowed": allowed,
            "action": action,
            "reason": "guardian_policy_satisfied" if allowed else block_reason,
            "simulated_only": True,
            "ml_authorized": False,
        }

    def _rejected_evaluation(
        self,
        *,
        reading_id: str,
        original: dict[str, Any],
        layer_a: dict[str, Any],
        reason: str,
        synthetic: bool,
    ) -> dict[str, Any]:
        city_brain = {
            "status": "blocked",
            "allowed": False,
            "action": "blocked",
            "reason": reason,
            "simulated_only": True,
            "ml_authorized": False,
        }
        ml = {
            "status": "skipped_security_gate",
            "model_available": None,
            "probability": None,
            "label": "Unavailable",
            "threshold": None,
            "uncertainty_band": None,
            "signals": [],
            "features": None,
            "error": "Layer A rejected the reading; inference was not called",
            "advisory_only": True,
        }
        self._event("ml_inference_skipped", reading_id, {"reason": reason})
        self._event("security_alert", reading_id, {
            "severity": "high",
            "reason_code": reason,
        })
        self._event("city_brain_decision", reading_id, dict(city_brain))
        return {
            "reading_id": reading_id,
            "sensor_id": original["sensor_id"],
            "timestamp": original["timestamp"],
            "sequence_number": original["sequence_number"],
            "domain": self._domain(original["sensor_type"]),
            "sensor_type": original["sensor_type"],
            "original_reading": original,
            "synthetic": synthetic,
            "incident_type": original["incident_type"],
            "layer_a": layer_a,
            "layer_b": {"status": "skipped", "reason": reason, "reason_codes": []},
            "layer_c": {"status": "skipped", "reason": reason},
            "ml": ml,
            "guardian": None,
            "reputation_change": None,
            "city_brain": city_brain,
            "action_blocked": True,
            "rejection_reason": reason,
        }

    def _contained_evaluation(
        self,
        reading: SensorReading,
        original: dict[str, Any],
        layer_a: dict[str, Any],
        verdict: TrustVerdict,
        reputation_before: float,
        raw_flags_before: int,
        synthetic: bool,
        incident_type: str | None,
    ) -> dict[str, Any]:
        ml = {
            "status": "skipped_contained",
            "model_available": None,
            "probability": None,
            "label": "Unavailable",
            "threshold": None,
            "uncertainty_band": None,
            "signals": [],
            "features": None,
            "error": "Contained sensors are not sent to model inference",
            "advisory_only": True,
        }
        city_brain = self._city_brain_decision(
            verdict, layer_a, {"status": "skipped"}, None
        )
        self._event("layer_b", reading.reading_id, {"status": "skipped_contained"})
        self._event("layer_c", reading.reading_id, {"status": "skipped_contained"})
        self._event("ml_inference_skipped", reading.reading_id, {"reason": "sensor_contained"})
        self._event("guardian_verdict", reading.reading_id, verdict.to_dict())
        self._event("city_brain_decision", reading.reading_id, dict(city_brain))
        return {
            "reading_id": reading.reading_id,
            "sensor_id": reading.sensor_id,
            "timestamp": reading.timestamp,
            "sequence_number": reading.sequence_number,
            "domain": self._domain(reading.sensor_type),
            "sensor_type": reading.sensor_type,
            "original_reading": original,
            "synthetic": synthetic,
            "incident_type": incident_type,
            "layer_a": layer_a,
            "layer_b": {"status": "skipped_contained", "reason_codes": []},
            "layer_c": {"status": "skipped_contained"},
            "ml": ml,
            "guardian": {
                **verdict.to_dict(),
                "scoring_breakdown": {
                    "starting_score": 1.0,
                    "penalties": [],
                    "final_score": 0.0,
                    "ml_numeric_contribution": 0.0,
                    "ml_treatment": "advisory_only_no_score_weight",
                },
            },
            "reputation_change": {
                "decayed_flags_before": reputation_before,
                "decayed_flags_after": self.reputation.recent_flags(reading.sensor_id),
                "raw_flags_before": raw_flags_before,
                "raw_flags_after": len(self.reputation.get(reading.sensor_id).flags),
            },
            "city_brain": city_brain,
            "action_blocked": True,
        }

    def _record(self, record: dict[str, Any]) -> None:
        validated = EvaluationRecord.model_validate(record).model_dump(mode="json")
        record.clear()
        record.update(validated)
        self.evaluations.append(record)

    def overview(self) -> dict[str, Any]:
        accepted = [e for e in self.evaluations if e["layer_a"]["status"] == "passed"]
        rejected = [e for e in self.evaluations if e["layer_a"]["status"] == "failed"]
        trusted = sum(1 for e in accepted if e["guardian"] and e["guardian"]["verdict"] == "trusted")
        suspicious = sum(1 for e in accepted if e["guardian"] and e["guardian"]["verdict"] != "trusted")
        incidents: dict[str, dict[str, Any]] = {}
        for record in self.evaluations:
            incident_type = record.get("incident_type")
            if incident_type:
                incident_key = f"{record['sensor_id']}:{incident_type}"
                incidents[incident_key] = {
                    "reading_id": record["reading_id"],
                    "incident_type": incident_type,
                    "sensor_id": record["sensor_id"],
                    "verdict": record["guardian"]["verdict"] if record["guardian"] else "rejected",
                    "city_brain": record["city_brain"]["status"],
                    "synthetic": record["synthetic"],
                }
        reputations = []
        for sensor_id in sorted(self.known_sensors):
            rep = self.reputation.get(sensor_id)
            reputations.append({
                "sensor_id": sensor_id,
                "decayed_flag_score": self.reputation.recent_flags(sensor_id),
                "raw_flag_count": len(rep.flags),
                "quarantined": rep.quarantined,
                "isolated": rep.isolated,
            })
        return {
            "guardian_status": "ready",
            "model_available": load_model_available(),
            "model_version": model_version(),
            "processed_readings": len(accepted),
            "trusted_readings": trusted,
            "suspicious_readings": suspicious,
            "rejected_readings": len(rejected),
            "active_simulated_incidents": list(incidents.values()),
            "sensor_reputation": reputations,
        }

    def timeline_snapshot(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(self.timeline[-limit:])


def load_model_available() -> bool:
    from app import load_model
    return load_model() is not None


def model_version() -> str:
    from app import METADATA
    return str(METADATA.get("model_version", "unknown"))


service = GuardianIntegration()
