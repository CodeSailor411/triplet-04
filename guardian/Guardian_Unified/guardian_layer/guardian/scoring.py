"""
Brings together Layers A-E into one TrustVerdict. This is the function
City Brain's get_trust_verdict() call ultimately runs.
"""

from .models import SensorReading, TrustVerdict
from .buffer import SensorBuffer
from .reputation import ReputationStore
from . import validation
from .correlation import check_correlation

TRUSTED_THRESHOLD = 0.7
SUSPECT_THRESHOLD = 0.3


def compute_trust_score(
    reading: SensorReading,
    buffer: SensorBuffer,
    reputation: ReputationStore,
    incident_type: str | None = None,
) -> TrustVerdict:
    score = 1.0
    reasons: list[str] = []

    history = buffer.history(reading.sensor_id)
    # exclude the current reading itself if it was already added before scoring
    history = [r for r in history if r.reading_id != reading.reading_id]

    # --- Layer B: physical plausibility ---
    if validation.violates_bounds(reading):
        score -= 0.5
        reasons.append("out_of_bounds")

    if validation.violates_rate_of_change(reading, history):
        score -= 0.35
        reasons.append("rate_of_change_exceeded")

    if validation.is_statistical_outlier(reading, history):
        score -= 0.25
        reasons.append("statistical_drift_outlier")

    # --- Layer C: correlation (only checked if this reading is claimed to
    #     signal an incident -- City Brain or the caller tells us which) ---
    if incident_type:
        result = check_correlation(incident_type, reading.timestamp, buffer)
        if result.expected and result.strength < 0.34:
            score -= 0.45
            reasons.append("no_correlated_evidence")
        elif result.expected and result.strength < 0.67:
            score -= 0.2
            reasons.append("weak_correlated_evidence")

    # --- Layer E: reputation history ---
    decayed_flags = reputation.recent_flags(reading.sensor_id)
    if decayed_flags > 0:
        score -= min(0.05 * decayed_flags, 0.25)
        reasons.append("prior_flags_on_record")

    score = max(0.0, min(1.0, score))

    if score > TRUSTED_THRESHOLD:
        verdict = "trusted"
    elif score > SUSPECT_THRESHOLD:
        verdict = "suspect"
    else:
        verdict = "compromised"

    if verdict != "trusted":
        reputation.record_flag(reading.sensor_id)

    return TrustVerdict(
        sensor_id=reading.sensor_id,
        reading_id=reading.reading_id,
        trust_score=score,
        verdict=verdict,
        reasons=reasons,
        timestamp=reading.timestamp,
    )
