"""Centralized Guardian classification and action risk policy."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class TrustPolicy:
    trusted_min: float = 0.7
    suspect_min: float = 0.3
    risk_minimums: dict[str, float] | None = None
    risk_values_provisional: bool = True

    def __post_init__(self):
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in (self.trusted_min, self.suspect_min)):
            raise ValueError("trust thresholds must be finite")
        if not 0 <= self.suspect_min < self.trusted_min <= 1:
            raise ValueError("thresholds must satisfy 0 <= suspect_min < trusted_min <= 1")
        values = self.risk_minimums or {"R1": .5, "R2": .7, "R3": .85}
        if set(values) != {"R1", "R2", "R3"}:
            raise ValueError("risk_minimums must define R1, R2, and R3")
        for risk, score in values.items():
            if (risk not in {"R1", "R2", "R3"} or isinstance(score, bool)
                    or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1):
                raise ValueError("risk minimums must be finite scores in [0,1] for R1/R2/R3")
        object.__setattr__(self, "risk_minimums", dict(values))

    def classify(self, score: float) -> Literal["trusted", "suspect", "compromised"]:
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("score must be finite and between 0 and 1")
        if score > self.trusted_min:
            return "trusted"
        if score > self.suspect_min:
            return "suspect"
        return "compromised"


def load_trust_policy(path: str | None = None) -> TrustPolicy:
    config_path = Path(path or os.environ.get("GUARDIAN_POLICY_FILE", Path(__file__).with_name("guardian_policy.json")))
    data = json.loads(config_path.read_text(encoding="utf-8"))
    trust = data["trust"]
    return TrustPolicy(
        trusted_min=float(trust["trusted_min"]), suspect_min=float(trust["suspect_min"]),
        risk_minimums={k: float(v) for k, v in trust["risk_minimums"].items()},
        risk_values_provisional=bool(trust.get("risk_values_provisional", True)),
    )
