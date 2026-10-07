from typing import Literal

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
    llm_mode: Literal["fixture", "gemini"] = "fixture"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    ai_timeout_seconds: float = 15
    ai_max_calls_per_run: int = 3
    peer_timeout_seconds: float = 5
