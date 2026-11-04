import pytest

from guardian_config import GuardianSettings


def test_settings_load_distinct_peer_credentials_and_overrides():
    settings = GuardianSettings.from_env({
        "TWIN_BASE_URL": "https://twin.example/",
        "GUARDIAN_TWIN_BEARER_KEY": "twin-only",
        "GUARDIAN_API_BEARER_KEY": "api-only",
        "GUARDIAN_BRAIN_MCP_BEARER_KEY": "brain-mcp-only",
        "GUARDIAN_BRAIN_BEARER_KEY": "brain-webhook-only",
        "GUARDIAN_R1_MIN_SCORE": "0.55",
        "TWIN_REPLAY_TICK_TOLERANCE": "7",
    })
    assert settings.twin_base_url == "https://twin.example"
    assert settings.twin_bearer_key != settings.api_bearer_key
    assert settings.brain_mcp_bearer_key != settings.brain_webhook_bearer_key
    assert settings.r1_min == .55
    assert settings.replay_tick_tolerance == 7


def test_settings_reject_inconsistent_risk_cutoffs():
    with pytest.raises(ValueError, match="R2 and R3"):
        GuardianSettings.from_env({"GUARDIAN_TRUSTED_MIN": ".75", "GUARDIAN_R2_MIN_SCORE": ".7"})
