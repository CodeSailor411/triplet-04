from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    brain_host: str = "127.0.0.1"
    brain_port: int = 8001
    brain_twin_caller_key: str = "dev-twin-to-brain"
    brain_guardian_caller_key: str = "dev-guardian-to-brain"
    brain_scenario_key: str = "dev-scenario-to-brain"
    twin_mcp_url: str = "http://127.0.0.1:8000/mcp"
    twin_brain_key: str = "dev-brain-to-twin"
    guardian_mcp_url: str = "http://127.0.0.1:8002/mcp"
    guardian_brain_key: str = "dev-brain-to-guardian"
    guardian_score_tool: str = "CONFIRM_WITH_9ANTRA"
    guardian_token_tool: str = "CONFIRM_WITH_9ANTRA"
    llm_mode: Literal["fixture", "gemini", "openrouter"] = "fixture"
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model: str = "gemini-3.5-flash-lite"
    ai_timeout_seconds: float = Field(default=15, gt=0, le=60)
    ai_max_calls_per_run: int = Field(default=3, ge=1, le=20)
    peer_timeout_seconds: float = Field(default=5, gt=0, le=30)

    peer_mode: Literal["fixture", "live"] = "fixture"
    brain_config_root: str = str(Path(__file__).resolve().parents[2])
    brain_fixture_case: str = "mocks/cases/air_quality/base_case.json"
    guardian_contract_confirmed: bool = False
    guardian_mapping_file: str = ""
    twin_preview_tool: str | None = None
    twin_commit_tool: str | None = None

    openrouter_api_key: str = Field(default="", repr=False)
    openrouter_model: str = "google/gemma-4-31b-it:free"
    brain_debug_enabled: bool = True
