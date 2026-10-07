"""Frozen shared types for five scenario modules. Only Elyes changes this file.

Twin-facing shapes follow twin-containment commit 40a7c90. Guardian adaptation
and the proposed Brain tool names still require partner confirmation.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

Domain = Literal["traffic", "water", "power", "air_quality", "emergency"]
Risk = Literal["R1", "R2", "R3"]
IncidentKind = Literal[
    "congestion", "road_accident", "flood", "low_water", "power_fault",
    "air_pollution", "fire", "medical",
]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class Capabilities(WireModel):
    layer: str
    layer_version: str
    ready: bool
    protocol_version: str
    required_protocol_version: str
    authenticated_as: str | None
    implemented_tools: list[str]
    planned_tools: list[str]


class Reading(WireModel):
    run_id: str = Field(min_length=1)
    reading_id: str = Field(min_length=1)
    tick: int = Field(ge=0)
    timestamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T.+Z$")
    node_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    sensor: str = Field(min_length=1)
    channel: str | None
    value: FiniteFloat | None
    unit: str


class ReadingsBatch(WireModel):
    run_id: str = Field(min_length=1)
    tick: int = Field(ge=0)
    time: str
    tick_seconds: FiniteFloat = Field(gt=0)
    count: int = Field(ge=0)
    readings: list[Reading]


class Node(WireModel):
    node_id: str
    domains: list[Domain] = Field(min_length=1)
    role: str
    actuators: list[str] = Field(default_factory=list)
    neighbours: list[str] = Field(default_factory=list)


class ActionInfo(WireModel):
    action: str
    domain: Domain
    risk: Risk | None
    preview_required: bool
    params: list[dict[str, Any]]
    target_nodes: list[str]
    action_cap: int | None


class Observation(WireModel):
    reading: Reading
    domains: list[Domain]
    usable: bool
    reason: str | None = None


class Incident(WireModel):
    incident_id: str
    kind: IncidentKind
    run_id: str
    domains: list[Domain]
    node_ids: list[str]
    source_reading_ids: list[str] = Field(min_length=1)
    facts: dict[str, Any] = Field(default_factory=dict)


class DetectionResult(WireModel):
    observations: list[Observation]
    incidents: list[Incident]
    warnings: list[str] = Field(default_factory=list)


class ActionProposal(BaseModel):
    # LLM outputs are stricter than peer input: no hidden token/tool fields.
    model_config = ConfigDict(extra="forbid", strict=True)
    action: str
    targets: list[str] = Field(min_length=1)
    params: dict[str, Any]
    risk: Risk | None
    preview_required: bool
    source_reading_ids: list[str] = Field(min_length=1)
    reason: str


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proposals: list[ActionProposal]
    alerts: list[str] = Field(default_factory=list)


class PlanningContext(WireModel):
    batch: ReadingsBatch
    incidents: list[Incident]
    nodes: list[Node]
    actions: list[ActionInfo]
    # Earlier persistence evidence is separate from the current-tick wire batch.
    evidence_readings: list[Reading] = Field(default_factory=list)


class TrustResult(WireModel):
    # Internal adapter shape, not an assertion about 9antra's wire format.
    score: FiniteFloat
    source_reading_ids: list[str]
    token: str | None = None
    code: str | None = None


class Decision(WireModel):
    decision_id: str
    run_id: str
    tick: int
    status: Literal["alert", "blocked", "pending", "committed", "rejected"]
    reason: str
    source_reading_ids: list[str]
    action: str | None = None
    targets: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    peer_code: str | None = None


class DecisionBatch(WireModel):
    run_id: str
    tick: int
    decisions: list[Decision]


class ContainmentNotice(WireModel):
    event_id: str
    run_id: str
    state: Literal["isolated", "quarantined", "corrected", "released"]
    device_ids: list[str]
    reading_ids: list[str] = Field(default_factory=list)
