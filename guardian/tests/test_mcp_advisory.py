"""Contract and model-parity checks for the Guardian advisory MCP tools."""
from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import app  # noqa: E402
from mcp import Client  # noqa: E402


WATER = {
    "Normal": {"domain": "water", "value": 62, "z_score": .3, "rate_of_change": .8, "out_of_bounds": 0, "correlation_strength": 1, "incident_claimed": 0, "decayed_flags": 0, "baseline_dev_norm": .01, "flat_run_len": 0},
    "Fake flood": {"domain": "water", "value": 180, "z_score": 45, "rate_of_change": 140, "out_of_bounds": 1, "correlation_strength": 0, "incident_claimed": 1, "decayed_flags": 0, "baseline_dev_norm": 1.4, "flat_run_len": 0},
    "Smart spoof": {"domain": "water", "value": 92, "z_score": 8, "rate_of_change": 42, "out_of_bounds": 0, "correlation_strength": 0, "incident_claimed": 1, "decayed_flags": 0, "baseline_dev_norm": .42, "flat_run_len": 0},
    "Stuck sensor": {"domain": "water", "value": 58.3, "z_score": 0, "rate_of_change": 0, "out_of_bounds": 0, "correlation_strength": 1, "incident_claimed": 0, "decayed_flags": 0, "baseline_dev_norm": 0, "flat_run_len": 5},
    "Adaptive ramp": {"domain": "water", "value": 78, "z_score": 1.4, "rate_of_change": 4.5, "out_of_bounds": 0, "correlation_strength": .85, "incident_claimed": 1, "decayed_flags": 0, "baseline_dev_norm": .35, "flat_run_len": 0},
}
EXPECTED_WATER = {
    "Normal": (.20, "Trusted"), "Fake flood": (1.00, "Suspicious"),
    "Smart spoof": (.82, "Suspicious"), "Stuck sensor": (.04, "Trusted"),
    "Adaptive ramp": (.56, "Uncertain"),
}
OTHER_DOMAIN_STATES = {
    "traffic": ["Trusted", "Suspicious", "Suspicious", "Trusted", "Trusted"],
    "power": ["Trusted", "Suspicious", "Suspicious", "Trusted", "Uncertain"],
    "air_quality": ["Trusted", "Suspicious", "Suspicious", "Trusted", "Uncertain"],
    "emergency": ["Trusted", "Suspicious", "Suspicious", "Trusted", "Uncertain"],
}


def call_tool(name, arguments):
    async def _call():
        async with Client(app.server) as client:
            return await client.call_tool(name, arguments)
    return asyncio.run(_call())


def payload(result):
    assert not result.is_error, result.content
    data = result.structured_content
    if data is None:
        import json
        data = json.loads(result.content[0].text)
    return data


def test_water_presets_match_prompt_probabilities_and_states():
    for name, reading in WATER.items():
        result = app.predict_reading(reading)
        expected_probability, expected_label = EXPECTED_WATER[name]
        assert abs(result.ml_probabilities.suspicious - expected_probability) <= .02, name
        assert result.ml_label == expected_label, name


def test_all_five_presets_have_expected_state_in_other_domains():
    config = app.SENSOR_CONFIG["domains"]
    for domain, expected_states in OTHER_DOMAIN_STATES.items():
        bounds = config[domain]
        for (name, profile), expected_state in zip(WATER.items(), expected_states):
            reading = dict(profile)
            reading["domain"] = domain
            fraction = (profile["value"] - 20) / (120 - 20)
            reading["value"] = bounds["lo"] + fraction * (bounds["hi"] - bounds["lo"])
            reading["rate_of_change"] = profile["rate_of_change"] / 6 * bounds["max_rate"]
            assert app.predict_reading(reading).ml_label == expected_state, f"{domain}/{name}"


def test_mcp_tool_matches_direct_model_for_60_random_readings():
    rng = random.Random(81427)
    domain_config = app.SENSOR_CONFIG["domains"]
    for _ in range(60):
        domain = rng.choice(sorted(domain_config))
        bounds = domain_config[domain]
        reading = {
            "domain": domain,
            "value": rng.uniform(bounds["lo"] - 10, bounds["hi"] + 10),
            "z_score": rng.uniform(-8, 8),
            "rate_of_change": rng.uniform(0, bounds["max_rate"] * 3),
            "out_of_bounds": rng.choice([0, 1]),
            "correlation_strength": rng.random(),
            "incident_claimed": rng.choice([0, 1]),
            "decayed_flags": rng.randint(0, 6),
            "baseline_dev_norm": rng.uniform(-1, 1),
            "flat_run_len": rng.randint(0, 8),
        }
        direct = app.predict_reading(reading)
        via_mcp = payload(call_tool("evaluate_reading_advisory", reading))
        assert via_mcp["ml_label"] == direct.ml_label
        assert abs(via_mcp["ml_probabilities"]["suspicious"] - direct.ml_probabilities.suspicious) <= 1e-6
        assert abs(via_mcp["ml_probabilities"]["trusted"] - direct.ml_probabilities.trusted) <= 1e-6


def test_mcp_rejects_missing_required_input_with_clear_error():
    result = call_tool("evaluate_reading_advisory", {"domain": "water"})
    assert result.is_error
    error_text = " ".join(part.text for part in result.content if part.type == "text")
    assert "Field required" in error_text
    assert "value" in error_text


def test_missing_value_is_unavailable_without_a_probability_and_unknown_fields_are_ignored():
    reading = dict(WATER["Normal"], value=None, ignored_client_field="ignored")
    output = payload(call_tool("evaluate_reading_advisory", reading))
    assert output["ml_label"] == "Unavailable"
    assert output["ml_probabilities"] is None
    assert output["advisory_only"] is True
    assert "trust_score" not in output and "action_token" not in output


def test_capabilities_publish_the_configured_protocol_threshold_and_band():
    output = payload(call_tool("describe_capabilities", {}))
    assert output["protocol_version"] == "2026-07-28"
    assert output["decision_threshold"] == app.DECISION_THRESHOLD
    assert output["uncertainty_band"] == app.UNCERTAINTY_BAND
    assert {"describe_capabilities", "evaluate_reading_advisory"} <= set(output["supported_tools"])
