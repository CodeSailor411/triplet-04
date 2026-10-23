"""Validated Guardian integration settings and peer-facing contract constants.

Names marked CONFIRM are placeholders pending partner approval; callers must
not interpret their presence here as confirmation that a peer exposes them.
"""
from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# CONFIRM with Twin: public MCP tool names and input/output schemas.
TWIN_TOOLS = {
    "list_actions": "list_actions",
    "get_clock": "get_clock",
    "list_nodes": "list_nodes",
    "get_containment_state": "get_containment_state",
    "preview_action": "preview_action",  # CONFIRM: safe preview tool name/schema
    "isolate": "isolate",  # CONFIRM: containment tool name/schema
    "quarantine": "quarantine",  # CONFIRM: containment tool name/schema
    "rollback": "rollback",  # CONFIRM: containment tool name/schema
    "release_device": "release_device",
    "get_readings": "get_readings",
    "actuate": "actuate",  # CONFIRM: execution-side tool, never called by Guardian
    "commit_action": "commit_action",  # CONFIRM: Brain/Twin two-step contract
}

# CONFIRM with CIVIS/Twin: stable public error vocabulary.
ERROR_CODES = {
    "cap_exceeded": "CAP_EXCEEDED",
    "device_quarantined": "DEVICE_QUARANTINED",
    "twin_unavailable": "TWIN_UNAVAILABLE",
    "preview_required": "PREVIEW_REQUIRED",
    "preview_failed": "PREVIEW_FAILED",
}

# CONFIRM with Twin: transport endpoint paths.
TWIN_SSE_PATH = "/events"
TWIN_MCP_PATH = "/mcp"


class GuardianSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=True)

    twin_base_url: str = Field(default="", alias="TWIN_BASE_URL")
    twin_bearer_key: str = Field(default="", alias="GUARDIAN_TWIN_BEARER_KEY")
    twin_mcp_timeout_seconds: float = Field(default=3.0, gt=0, alias="TWIN_MCP_TIMEOUT_SECONDS")
    brain_mcp_bearer_key: str = Field(default="", alias="GUARDIAN_BRAIN_MCP_BEARER_KEY")
    api_bearer_key: str = Field(default="", alias="GUARDIAN_API_BEARER_KEY")
    brain_webhook_bearer_key: str = Field(default="", alias="GUARDIAN_BRAIN_BEARER_KEY")
    trusted_min: float = Field(default=.7, ge=0, le=1, alias="GUARDIAN_TRUSTED_MIN")
    degraded_min: float = Field(default=.3, ge=0, le=1, alias="GUARDIAN_DEGRADED_MIN")
    r1_min: float = Field(default=.5, ge=0, le=1, alias="GUARDIAN_R1_MIN_SCORE")
    r2_min: float = Field(default=.7, ge=0, le=1, alias="GUARDIAN_R2_MIN_SCORE")
    r3_min: float = Field(default=.85, ge=0, le=1, alias="GUARDIAN_R3_MIN_SCORE")
    replay_tick_tolerance: int = Field(default=100, ge=0, alias="TWIN_REPLAY_TICK_TOLERANCE")

    @model_validator(mode="after")
    def validate_policy(self):
        if not self.degraded_min < self.trusted_min:
            raise ValueError("Guardian cutoffs must satisfy degraded_min < trusted_min")
        if self.r2_min < self.trusted_min or self.r3_min < self.trusted_min:
            raise ValueError("R2 and R3 minimums must be at or above the Trusted cutoff")
        self.twin_base_url = self.twin_base_url.rstrip("/")
        return self

    @classmethod
    def from_env(cls, env=None):
        if env is None:
            return cls()
        return cls(**dict(env))
