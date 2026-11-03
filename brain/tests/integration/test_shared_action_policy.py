"""Shared actuator regression, independent of undelivered S07 detector code."""

import pytest

from civis_brain.contracts import ReadingsBatch
from civis_brain.integration.runtime import ACTION_BY_SCENARIO

from .helpers import harness, make_case
from .test_oct19 import advance


@pytest.mark.parametrize("latest_value,expected", [(50.0, "blocked"), (90.0, "committed")])
@pytest.mark.parametrize("phase", ["planning", "approval"])
async def test_shared_action_keeps_originating_scenario_policy(
    monkeypatch, latest_value, expected, phase
):
    case = make_case("S02")
    case["policy"].update(sensor="water_level", threshold_min=80.0)
    runtime, twin, guardian, provider = harness(case)
    # A second scenario shares the action and appears first in the mapping.
    # It is deliberately not a substitute for Mariem's actual S07 module.
    monkeypatch.setitem(ACTION_BY_SCENARIO, "S01", "set_valve_position")
    runtime.policies["S01"] = {"sensor": "water_level", "threshold_min": 0.0}

    def newer_evidence():
        raw = advance(case["batches"][0])
        raw["readings"][0]["value"] = latest_value
        twin.advance(raw)
        runtime.observe_feed(ReadingsBatch.model_validate(raw))

    original_plan = provider.generate
    original_guardian = guardian.call_tool

    async def plan(context):
        result = await original_plan(context)
        if phase == "planning":
            newer_evidence()
        return result

    async def authorize(name, arguments):
        result = await original_guardian(name, arguments)
        if phase == "approval" and name == "fixture_approve":
            newer_evidence()
        return result

    provider.generate = plan
    guardian.call_tool = authorize
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].status == expected
    assert len(twin.effects) == int(expected == "committed")
    if expected == "blocked":
        assert result.decisions[0].peer_code == "EVIDENCE_CHANGED"
