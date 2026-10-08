import json
from pathlib import Path

import pytest
from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.contracts import ReadingsBatch
from civis_brain.integration.runtime import build_runtime

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("domain,sid", [("power", "S03"), ("air_quality", "S04")])
@pytest.mark.parametrize("variant", ["base", "refusal"])
async def test_actual_registered_case(domain, sid, variant, tmp_path):
    case = json.loads((ROOT / "mocks/cases" / domain / f"{variant}_case.json").read_text())
    twin, guardian, provider = FixtureTwin(case), FixtureGuardian(case), FixturePlanProvider(case)
    runtime = build_runtime(
        twin=twin,
        guardian=guardian,
        provider=provider,
        policies={sid: case["policy"]},
        features={
            "enabled_scenario_ids": [sid],
            "guardian_score_tool": "fixture_score",
            "guardian_token_tool": "fixture_approve",
        },
        artifact_dir=tmp_path,
    )
    for raw in case["batches"]:
        batch = ReadingsBatch.model_validate(raw)
        twin.advance(batch)
        result = await runtime.evaluate_tick(batch)
    assert [row.status for row in result.decisions] == case["expected"]["final_statuses"]
    assert not twin.effects and not provider.calls
    assert all(row["name"] != "actuate" for row in twin.calls)
    assert (tmp_path / "trace.jsonl").exists()
    if domain == "air_quality" and variant == "base":
        assert result.decisions[0].source_reading_ids == ["AQ-01-1", "AQ-01-2"]
        scores = next(row for row in guardian.calls if row["name"] == "fixture_score")
        assert len(scores["arguments"]["readings"]) == 2


async def test_unrelated_batch_has_no_power_or_medical_decision():
    case = json.loads((ROOT / "mocks/cases/air_quality/base_case.json").read_text())
    twin, guardian, provider = FixtureTwin(case), FixtureGuardian(case), FixturePlanProvider(case)
    power = json.loads((ROOT / "config/scenarios/power.json").read_text())
    runtime = build_runtime(
        twin=twin,
        guardian=guardian,
        provider=provider,
        policies={"S03": power, "S04": case["policy"]},
        features={"guardian_score_tool": "fixture_score", "guardian_token_tool": "fixture_approve"},
    )
    for raw in case["batches"]:
        batch = ReadingsBatch.model_validate(raw)
        twin.advance(batch)
        result = await runtime.evaluate_tick(batch)
    assert len(result.decisions) == 1 and result.decisions[0].status == "alert"
    assert result.decisions[0].peer_code is None and not twin.effects and not provider.calls
