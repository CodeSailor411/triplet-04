"""Canonical typed API and evaluation-record schemas."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


class OriginalReading(BaseModel):
    reading_id: str | None
    sensor_id: str
    sensor_type: str
    value: FiniteFloat
    unit: str
    timestamp: FiniteFloat
    sequence_number: int
    location: dict[str, FiniteFloat]
    incident_type: str | None
    require_signature: bool
    signature_present: bool


class LayerAResult(BaseModel):
    status: Literal["passed", "failed"]
    replay: Literal["passed", "failed"]
    signature: Literal["not_required", "present_not_required", "verified", "failed"]
    reason_codes: list[str]


class LayerBResult(BaseModel):
    status: Literal["passed", "failed", "skipped", "skipped_contained"]
    checks: dict[str, str] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    flat_run_length: int | None = None
    reason: str | None = None


class LayerCResult(BaseModel):
    status: Literal["passed", "failed", "uncertain", "not_applicable", "skipped", "skipped_contained"]
    expected: bool | None = None
    found: bool | None = None
    strength: FiniteFloat | None = None
    checked: list[str] = Field(default_factory=list)
    reason: str | None = None


class ModelAdvisory(BaseModel):
    status: Literal["available", "unavailable", "error", "skipped_security_gate", "skipped_contained"]
    model_available: bool | None
    probability: FiniteFloat | None
    label: str
    threshold: FiniteFloat | None
    uncertainty_band: FiniteFloat | None
    signals: list[str] = Field(default_factory=list)
    features: dict[str, str | int | float] | None
    error: str | None
    model_version: str | None = None
    advisory_only: Literal[True]


class ScoringPenalty(BaseModel):
    reason_code: str
    penalty: FiniteFloat


class ScoringBreakdown(BaseModel):
    starting_score: FiniteFloat
    penalties: list[ScoringPenalty] = Field(default_factory=list)
    final_score: FiniteFloat
    ml_numeric_contribution: Literal[0.0]
    ml_treatment: Literal["advisory_only_no_score_weight"]


class GuardianVerdict(BaseModel):
    sensor_id: str
    reading_id: str
    trust_score: FiniteFloat
    verdict: Literal["trusted", "suspect", "compromised"]
    reasons: list[str] = Field(default_factory=list)
    timestamp: FiniteFloat
    history_requirement: dict[str, int] = Field(default_factory=dict)
    scoring_breakdown: ScoringBreakdown


class ReputationChange(BaseModel):
    decayed_flags_before: FiniteFloat
    decayed_flags_after: FiniteFloat
    raw_flags_before: int
    raw_flags_after: int


class CityBrainDecision(BaseModel):
    status: Literal["allowed", "blocked"]
    allowed: bool
    action: str
    reason: str
    simulated_only: Literal[True]
    ml_authorized: Literal[False]


class EvaluationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reading_id: str
    sensor_id: str
    timestamp: FiniteFloat
    sequence_number: int
    domain: str | None
    sensor_type: str
    original_reading: OriginalReading
    synthetic: bool
    incident_type: str | None
    layer_a: LayerAResult
    layer_b: LayerBResult
    layer_c: LayerCResult
    ml: ModelAdvisory
    guardian: GuardianVerdict | None
    reputation_change: ReputationChange | None
    city_brain: CityBrainDecision
    action_blocked: bool
    rejection_reason: str | None = None
